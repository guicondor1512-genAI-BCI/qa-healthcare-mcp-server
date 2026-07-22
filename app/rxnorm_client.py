"""Cliente MCP do servidor RxNorm externo (medical-mcp, stdio).

Isola a camada de rede: abre uma sessao stdio por chamada, invoca a tool
`search-drug-nomenclature` e retorna o texto agregado do resultado. Resiliencia
(timeout/circuit breaker) e responsabilidade do orquestrador.

Config por env var:
  RXNORM_MCP_COMMAND  comando do servidor (default: npx)
  RXNORM_MCP_ARGS     argumentos separados por espaco (default: -y medical-mcp)
"""
from __future__ import annotations

import os
import shlex

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_TOOL_NAME = "search-drug-nomenclature"


def _server_params() -> StdioServerParameters:
    command = os.environ.get("RXNORM_MCP_COMMAND", "npx")
    args = shlex.split(os.environ.get("RXNORM_MCP_ARGS", "-y medical-mcp"))
    return StdioServerParameters(command=command, args=args)


async def normalize_drug(name: str) -> str:
    """Invoca a tool RxNorm e retorna o texto agregado do content."""
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(_TOOL_NAME, {"query": name})
    return "".join(
        block.text for block in result.content if getattr(block, "type", None) == "text"
    )
