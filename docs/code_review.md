# Code Review — qa-healthcare-mcp-server

**Date:** 2026-07-12
**Scope:** The `mcp-server` microservice in isolation — the MCP tool layer (`app/tools.py`), the FastAPI façade (`app/main.py`), `Dockerfile`, `requirements.txt`, `pytest.ini`, `.github/workflows/ci.yml`, and `tests/test_tools.py`. Service role: clinical MCP tools (`drug_lookup`, `interaction_check`) exposed on host port 8010 (container 8000), called by the orchestrator.
**Method:** Full read of every source file (~145 lines). Each claim carries a `file:line` reference and a CONFIRMED / POSSIBLE tag; behavioral claims were reproduced by executing the handlers directly (see notes). Prior platform-wide review (`qa-healthcare-deploy/docs/code_review.md`, 2026-07-11) findings M12, M13, L12 were re-verified against the *current* source. `pytest -q` was run.

> Grouped by severity; prioritized action plan at the end. `file:line` references are clickable.

---

## Executive summary

This is a tiny, clean, dependency-light service: two pure-function tools over an in-memory dictionary, wrapped in a two-endpoint FastAPI app. It runs, the suite passes (`3 passed`), and the MCP shape (`/mcp/tools`, `/mcp/call`) is correct. The dominant risks are **clinical-correctness of the tool outputs**, not infrastructure:

1. **`interaction_check` cannot tell "unknown/misspelled drug" from "known-safe pair."** Both return `interaction: False` with the same reassuring note. For a clinical tool, a typo silently becomes a false "no known interaction" — a real patient-safety failure mode. (**M12, still open**)
2. **Input validation is delegated entirely to Python's argument binding.** `call_tool(**arguments)` splats an unvalidated caller dict into the handler. `TypeError` (missing/extra args) is now caught and mapped to 422, but a **non-string argument value** (e.g. `{"name": 123}`) raises `AttributeError` at `.strip()`, which is *not* caught → unhandled 500. The `input_schema` is declared but never enforced. (**M13, partially addressed**)
3. **Raw exception text is returned to the caller as the HTTP `detail`.** Internal-leak surface, and inconsistent contract. (**L12, still open**)

All three prior MCP findings remain effectively **OPEN** (M13 only partly mitigated). No prior MCP finding is fully fixed. Beyond those, the review surfaces one new medium (no `response_model` / declared error contract on the endpoints) and several lows.

**Severity counts:** 0 Critical · 0 High · 3 Medium · 4 Low.

`pytest -q` → **3 passed in 0.07s** (`tests/test_tools.py`). Suite exercises only happy paths.

---

## Medium

**[M12] `interaction_check` conflates unknown/misspelled drugs with a genuinely-safe pair (clinical risk)** — `app/tools.py:31-34` — CONFIRMED (reproduced: `interaction_check(drug_a="aspirinaXX", drug_b="naoexiste")` → `{"interaction": False, "note": "Sem interação conhecida na base."}` — byte-for-byte identical to a real known-safe pair). The function only looks up the `frozenset` key; it never checks either drug against `_DRUGS`. A caller (or the orchestrator, or ultimately the patient) reading "Sem interação conhecida na base" has no way to know the answer is "we don't recognize one of these drugs" vs. "these two are safe together." A typo in a drug name silently downgrades to a false-reassuring negative. **Unchanged since the prior review.** **Action:** validate both drugs against `_DRUGS` first; when either is unknown return an explicit signal, e.g. `{"interaction": None, "unknown_drug": ["aspirinaxx"], "note": "Medicamento(s) não reconhecido(s) na base: aspirinaXX — não é possível avaliar interação."}`. Keep `interaction: False` reserved for the case where **both** drugs are known and no interaction is recorded. Do the same defensive check in `drug_lookup` messaging (it already returns `found: False`, which is correct — mirror that clarity here).

**[M13] `call_tool(**arguments)` splats an unvalidated caller dict; non-string values escape the 422 mapping → 500** — `app/tools.py:63-67`, `app/main.py:34-42` — CONFIRMED (reproduced). Progress since the prior review: `app/main.py:40` now catches `TypeError` and maps it to 422, so **missing** (`{}` → `missing 1 required positional argument`) and **extra** (`{"name":"x","foo":1}` → `unexpected keyword argument 'foo'`) arguments now return 422 instead of 500. **But** a well-shaped dict with a wrong-typed value slips through: `call_tool("drug_lookup", {"name": 123})` reaches `123.strip()` and raises `AttributeError`, which `app/main.py` does **not** catch → unhandled 500. The declared `input_schema` (`app/tools.py:41,46-50`) is advertised via `/mcp/tools` but **never used to validate** input. Relying on `**arguments` + Python's binder for validation is fragile: it enforces arity but not types, and couples the HTTP status to Python-internal exception types. **Action:** validate `arguments` against the tool's `input_schema` before dispatch — add `jsonschema` and `jsonschema.validate(arguments, TOOLS[name]["input_schema"])`, raising a 422 with a schema-derived (not exception-text) message on failure. Alternatively/additionally, back each tool with a Pydantic model so FastAPI produces a structured 422. At minimum, broaden the `app/main.py` `except` to also catch `AttributeError`/`ValueError` so no handler bug becomes a 500. **Partially addressed; core gap (non-string → 500, schema unenforced) still open.**

**[M14 — NEW] Endpoints declare no `response_model` and no documented error contract** — `app/main.py:24-42` — CONFIRMED. `/mcp/tools` and `/mcp/call` return bare `-> dict`; there is no `response_model`, so the OpenAPI schema is untyped and the success/error shapes are undocumented for the orchestrator. The 404/422 responses are produced ad hoc from caught exceptions with no declared `responses=` metadata. Low functional impact (the orchestrator degrades gracefully per platform design) but it weakens the service-contract clarity the platform relies on for cross-repo consistency. **Action:** add explicit Pydantic response models (`ToolsResponse`, `CallResponse`) and declare `responses={404: ..., 422: ...}` on `/mcp/call`; this also lets you emit a stable error envelope instead of raw exception strings (see L12).

---

## Low

**[L12] `/mcp/call` returns raw exception text as `detail` (internal leak / unstable contract)** — `app/main.py:38-41` — CONFIRMED. Both handlers pass `detail=str(exc)` straight through: the 404 leaks the internal message `"tool desconhecida: <name>"` and the 422 leaks Python binder text like `"tool_drug_lookup() got an unexpected keyword argument 'foo'"` — implementation details (internal function names, argument internals) surfaced to the caller. Low severity because this is an internal service and the data isn't PHI, but it is an unstable contract and an information-leak habit. **Unchanged since the prior review.** **Action:** return a fixed, caller-safe message (e.g. `{"detail": "tool desconhecida"}` / `{"detail": "argumentos inválidos"}`), and log the raw exception server-side.

**[L22 — NEW] `EXPOSE 8000` but the platform maps host 8010 — documentation drift risk** — `Dockerfile:7` — CONFIRMED (informational). The container listens on 8000 and is published as `8010:8000` by compose/README; `EXPOSE 8000` is technically correct (it documents the *container* port) but easy to misread given the service's "port 8010" identity. No action strictly required. **Action (optional):** add a comment noting the external 8010 mapping.

**[L23 — NEW] No input-size bounds on tool arguments** — `app/tools.py:26-34`, `app/main.py:19-21` — CONFIRMED. `CallReq.arguments` accepts an arbitrary dict and drug-name strings are unbounded. Not exploitable here (pure dict lookups, no regex/DB), but a defensive `max_length` on the string fields (once Pydantic-modeled per M13) bounds abuse and keeps the contract tight. **Action:** cap argument string lengths when you introduce per-tool Pydantic/`jsonschema` validation.

**[L24 — NEW] `Callable` import unused-ish / handlers untyped for arg shape** — `app/tools.py:10,66` — POSSIBLE (style only). `handler: Callable[..., dict[str, Any]]` is annotated with `...` args, so the type checker cannot catch a bad `**arguments` splat — consistent with M13's root cause. No functional bug. **Action:** none required; superseded by M13's schema-validation fix.

---

## Verified fixed since prior review

Re-checked all three prior MCP findings against current source:

- **M12** — NOT fixed. `app/tools.py:31-34` unchanged; unknown drugs still indistinguishable from safe pairs (reproduced).
- **M13** — PARTIALLY fixed. `app/main.py:40` now maps `TypeError` → 422 (missing/extra args handled), but non-string argument values still raise an uncaught `AttributeError` → 500, and the `input_schema` is still not enforced (reproduced). Core finding stays OPEN.
- **L12** — NOT fixed. `app/main.py:38-41` still returns `str(exc)` as `detail`.

**Net: 0 of 3 prior findings fully closed; 1 partially mitigated.**

---

## Test-coverage gaps

`tests/test_tools.py` (3 tests) covers only: list contains both tools, a successful `drug_lookup`, and one positive `interaction_check`. It calls the tool functions directly — **the FastAPI layer (`/mcp/call`, `/mcp/tools`, error mapping) is entirely untested.** Missing, in priority order:

- **`interaction_check` with an unknown/misspelled drug** — pins M12 (assert an `unknown_drug` signal, not a false `interaction: False`).
- **`interaction_check` symmetric key** — assert `(a,b)` and `(b,a)` return the same note (the `frozenset` key already makes this true — a test would lock it in; reproduced working).
- **Unknown tool → HTTP 404** via `TestClient` on `/mcp/call`.
- **Bad/missing arguments → HTTP 422** (missing required, extra key) and **non-string value** (should be 422, currently 500 — this test would fail today and pin M13).
- **`drug_lookup` not-found path** (`found: False`).
- **No `httpx`/`TestClient`-based test exists at all** despite `httpx` being a declared dependency (`requirements.txt:4`); add `starlette.testclient`/`httpx` HTTP-level tests.

---

## Prioritized action plan

### P0 — clinical correctness
1. **[M12]** Make `interaction_check` return an explicit `unknown_drug` signal; reserve `interaction: False` for two *known* drugs with no recorded interaction. Add the unknown-drug + symmetric-key tests.

### P1 — input validation & error contract
2. **[M13]** Validate `arguments` against each tool's `input_schema` (jsonschema) or per-tool Pydantic models before dispatch; broaden `app/main.py`'s `except` so a handler bug can never become a 500. Add the bad-args/non-string 422 tests.
3. **[L12]** Replace `detail=str(exc)` with fixed caller-safe messages; log raw exceptions server-side.

### P2 — contract & robustness polish
4. **[M14]** Add `response_model`s and declared `responses=` metadata to both endpoints.
5. **[L23]** Cap argument string lengths once tools are Pydantic/jsonschema-validated.
6. **Tests:** add HTTP-level (`TestClient`) coverage for 404/422/happy paths; several would fail today and pin the fixes above.

---

*Reviewed against current source on 2026-07-12; behavioral claims (M12, M13) reproduced by direct handler execution. `pytest -q` → 3 passed.*
