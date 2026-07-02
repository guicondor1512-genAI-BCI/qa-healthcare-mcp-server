"""MCP Server — ferramentas de healthcare (spec §4, §10).

Implementa um subconjunto do Model Context Protocol suficiente para o orquestrador:
listar tools e invocá-las. As tools operam sobre uma base local de exemplo; em
produção chamariam APIs externas (bulário, RxNorm, DrugBank), protegidas pelos
guardrails operacionais (circuit breaker/timeout) do orquestrador.
"""
from __future__ import annotations

from typing import Any, Callable

# ---- Base de exemplo ----
_DRUGS: dict[str, dict[str, Any]] = {
    "sertralina": {"classe": "ISRS", "dose_inicial": "50 mg/dia", "indicacao": "depressão, ansiedade"},
    "fluoxetina": {"classe": "ISRS", "dose_inicial": "20 mg/dia", "indicacao": "depressão"},
    "ibuprofeno": {"classe": "AINE", "dose_inicial": "200-400 mg", "indicacao": "febre, dor"},
    "semaglutida": {"classe": "agonista GLP-1", "dose_inicial": "0,25 mg/semana", "indicacao": "peso, DM2"},
}

_INTERACTIONS: dict[frozenset[str], str] = {
    frozenset({"sertralina", "ibuprofeno"}): "Risco aumentado de sangramento GI; usar com cautela.",
    frozenset({"sertralina", "fluoxetina"}): "Ambos ISRS: risco de síndrome serotoninérgica.",
}


def tool_drug_lookup(name: str) -> dict[str, Any]:
    info = _DRUGS.get(name.strip().lower())
    return {"found": info is not None, "drug": name, "info": info or {}}


def tool_interaction_check(drug_a: str, drug_b: str) -> dict[str, Any]:
    key = frozenset({drug_a.strip().lower(), drug_b.strip().lower()})
    note = _INTERACTIONS.get(key)
    return {"pair": [drug_a, drug_b], "interaction": note is not None, "note": note or "Sem interação conhecida na base."}


# ---- Registro de tools no estilo MCP ----
TOOLS: dict[str, dict[str, Any]] = {
    "drug_lookup": {
        "description": "Consulta classe, dose inicial e indicação de um medicamento.",
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


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name not in TOOLS:
        raise KeyError(f"tool desconhecida: {name}")
    handler: Callable[..., dict[str, Any]] = TOOLS[name]["handler"]
    return handler(**arguments)
