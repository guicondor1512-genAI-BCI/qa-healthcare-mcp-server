"""Cliente MCP do servidor RxNorm externo (medical-mcp, stdio).

Isola a camada de rede: abre uma sessao stdio por chamada, invoca a tool
`search-drug-nomenclature` e retorna o texto agregado do resultado. Resiliencia
(timeout/circuit breaker) e responsabilidade do orquestrador.

Config por env var (a imagem Docker define os defaults de produção):
  RXNORM_MCP_COMMAND  comando do servidor (default: python)
  RXNORM_MCP_ARGS     argumentos separados por espaco (default: rxnorm_mcp_server.py)

Nota: o medical-mcp da comunidade nao funciona por stdio (polui o stdout com um
banner e quebra o handshake JSON-RPC); usamos rxnorm_mcp_server.py, compativel.
"""
from __future__ import annotations

import os
import shlex

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_TOOL_NAME = "search-drug-nomenclature"


def _server_params() -> StdioServerParameters:
    command = os.environ.get("RXNORM_MCP_COMMAND", "python")
    args = shlex.split(os.environ.get("RXNORM_MCP_ARGS", "rxnorm_mcp_server.py"))
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
