"""Servidor MCP RxNorm minimo e compativel (stdio).

Expoe a tool `search-drug-nomenclature` batendo no RxNav real
(GET /REST/drugs.json), no mesmo formato de texto que o cliente espera.

Motivo de existir: o medical-mcp da comunidade escreve um banner no stdout ao
iniciar, o que viola o contrato stdio do MCP (stdout = so JSON-RPC) e quebra o
handshake. Este servidor mantem o stdout limpo.
"""
from __future__ import annotations

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("rxnorm")

_RXNAV = "https://rxnav.nlm.nih.gov/REST/drugs.json"


@mcp.tool(name="search-drug-nomenclature")
async def search_drug_nomenclature(query: str) -> str:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(_RXNAV, params={"name": query})
        resp.raise_for_status()
        data = resp.json()

    concepts = []
    for group in data.get("drugGroup", {}).get("conceptGroup") or []:
        concepts.extend(group.get("conceptProperties") or [])

    if not concepts:
        return f'No drugs found for "{query}".'

    lines = [f'Found {len(concepts)} drugs for "{query}":', ""]
    for i, c in enumerate(concepts, 1):
        lines.append(f"{i}. **{c.get('name', '')}**")
        lines.append(f"   RxCUI: {c.get('rxcui', '')}")
        lines.append(f"   Term Type: {c.get('tty', '')}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
