"""MCP Server — ferramentas de healthcare (spec §4, §10).

Implementa um subconjunto do Model Context Protocol suficiente para o orquestrador:
listar tools e invocá-las. `drug_lookup` atua como cliente MCP de um servidor RxNorm
externo (medical-mcp/stdio, ver rxnorm_client); `interaction_check` usa uma base local
de interações (o RxNorm não oferece checagem de interação). A resiliência
(circuit breaker/timeout) é responsabilidade do orquestrador.
"""
from __future__ import annotations

import inspect
import re
from typing import Any, Callable

from . import rxnorm_client

# ---- Interacoes: base local (RxNorm nao oferece checagem de interacao) ----
_INTERACTIONS: dict[frozenset[str], str] = {
    frozenset({"sertralina", "ibuprofeno"}): "Risco aumentado de sangramento GI; usar com cautela.",
    frozenset({"sertralina", "fluoxetina"}): "Ambos ISRS: risco de síndrome serotoninérgica.",
}

# Fármacos que a base de interação conhece: os que aparecem em algum par.
# Só é seguro afirmar "sem interação" quando AMBOS estão neste conjunto.
_KNOWN_DRUGS: frozenset[str] = frozenset().union(*_INTERACTIONS.keys())

# ---- Parsing do texto RxNorm (search-drug-nomenclature) ----
_RXCUI_RE = re.compile(r"RxCUI:\s*(\d+)")
_NAME_RE = re.compile(r"\*\*(.+?)\*\*")


def _parse_rxnorm(text: str) -> dict[str, Any] | None:
    """Extrai o primeiro conceito RxNorm do texto; None se nao houver RxCUI."""
    rxcui = _RXCUI_RE.search(text)
    if rxcui is None:
        return None
    name = _NAME_RE.search(text)
    return {
        "rxcui": rxcui.group(1),
        "normalized_name": name.group(1).strip() if name else "",
        "rxnorm_text": text,
    }


async def tool_drug_lookup(name: str) -> dict[str, Any]:
    text = await rxnorm_client.normalize_drug(name)
    info = _parse_rxnorm(text)
    found = info is not None
    return {
        "found": found,
        "status": "found" if found else "unknown_drug",
        "drug": name,
        "info": info or {},
    }


def tool_interaction_check(drug_a: str, drug_b: str) -> dict[str, Any]:
    norm_a = drug_a.strip().lower()
    norm_b = drug_b.strip().lower()

    # M12: distinguir "medicamento desconhecido/erro de digitação" de "par seguro conhecido".
    # Só é seguro afirmar "sem interação" quando AMBOS os fármacos existem na base.
    unknown = [orig for orig, norm in ((drug_a, norm_a), (drug_b, norm_b)) if norm not in _KNOWN_DRUGS]
    if unknown:
        return {
            "pair": [drug_a, drug_b],
            "status": "unknown_drug",
            "interaction": None,
            "unknown_drug": unknown,
            "note": (
                "Medicamento(s) não reconhecido(s) na base: "
                + ", ".join(unknown)
                + " — não é possível avaliar a interação."
            ),
        }

    note = _INTERACTIONS.get(frozenset({norm_a, norm_b}))
    return {
        "pair": [drug_a, drug_b],
        "status": "interaction" if note is not None else "no_interaction",
        "interaction": note is not None,
        "note": note or "Sem interação conhecida na base.",
    }


# ---- Registro de tools no estilo MCP ----
TOOLS: dict[str, dict[str, Any]] = {
    "drug_lookup": {
        "description": "Normaliza um medicamento no RxNorm (RxCUI e nome padronizado).",
        "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        "handler": tool_drug_lookup,
    },
    "interaction_check": {
        "description": "Verifica interação entre dois medicamentos.",
        "input_schema": {
            "type": "object",
            "properties": {"drug_a": {"type": "string"}, "drug_b": {"type": "string"}},
            "required": ["drug_a", "drug_b"],
        },
        "handler": tool_interaction_check,
    },
}


def list_tools() -> list[dict[str, Any]]:
    return [
        {"name": name, "description": t["description"], "input_schema": t["input_schema"]}
        for name, t in TOOLS.items()
    ]


# M13/L23: validação determinística dos argumentos contra o input_schema declarado,
# ANTES de fazer o splat `**arguments` no handler. Evita que um valor não-string
# (ex.: {"name": 123}) chegue ao `.strip()` e derrube o handler com AttributeError → 500.
# Validador mínimo (sem dependência externa) para o subconjunto de schema que usamos:
# type=object, properties com type=string, required. Limite de tamanho defensivo.
_MAX_ARG_LEN = 256


class ArgumentValidationError(ValueError):
    """Argumentos inválidos para a tool (não conformes ao input_schema)."""


def _validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    if not isinstance(arguments, dict):
        raise ArgumentValidationError("argumentos devem ser um objeto")
    properties: dict[str, Any] = schema.get("properties", {})
    required: list[str] = schema.get("required", [])

    for field in required:
        if field not in arguments:
            raise ArgumentValidationError(f"campo obrigatório ausente: {field}")

    for key, value in arguments.items():
        if key not in properties:
            raise ArgumentValidationError(f"argumento inesperado: {key}")
        expected = properties[key].get("type")
        if expected == "string":
            if not isinstance(value, str):
                raise ArgumentValidationError(f"campo '{key}' deve ser string")
            if len(value) > _MAX_ARG_LEN:
                raise ArgumentValidationError(f"campo '{key}' excede o tamanho máximo")


async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name not in TOOLS:
        raise KeyError(f"tool desconhecida: {name}")
    tool = TOOLS[name]
    _validate_arguments(tool["input_schema"], arguments)
    handler: Callable[..., Any] = tool["handler"]
    result = handler(**arguments)
    if inspect.isawaitable(result):
        result = await result
    return result
