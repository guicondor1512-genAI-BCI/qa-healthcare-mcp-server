"""MCP Server (FastAPI) — spec §4, §10.

Endpoints:
  GET  /mcp/tools      -> lista as tools disponíveis (nome, descrição, schema)
  POST /mcp/call       -> invoca uma tool com argumentos
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .tools import ArgumentValidationError, call_tool, list_tools

logger = logging.getLogger("mcp-server")

app = FastAPI(title="QA Healthcare — MCP Server", version="0.1.0")


class CallReq(BaseModel):
    name: str
    arguments: dict[str, Any] = {}


# M14: modelos de resposta explícitos para documentar o contrato no OpenAPI.
class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


class ToolsResponse(BaseModel):
    tools: list[ToolSpec]


class CallResponse(BaseModel):
    name: str
    result: dict[str, Any]


class ErrorResponse(BaseModel):
    detail: str


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "tools": [t["name"] for t in list_tools()]}


@app.get("/mcp/tools", response_model=ToolsResponse)
async def tools() -> dict:
    return {"tools": list_tools()}


@app.post(
    "/mcp/call",
    response_model=CallResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Tool desconhecida"},
        422: {"model": ErrorResponse, "description": "Argumentos inválidos"},
    },
)
async def call(req: CallReq) -> dict:
    try:
        result = await call_tool(req.name, req.arguments)
    except KeyError as exc:
        # L12: mensagem fixa e segura ao chamador; detalhe bruto só no log do servidor.
        logger.warning("tool desconhecida: %s", req.name)
        raise HTTPException(status_code=404, detail="tool desconhecida") from exc
    except (ArgumentValidationError, TypeError, ValueError) as exc:
        # M13: qualquer violação de contrato de argumentos vira 422 (nunca 500).
        logger.warning("argumentos inválidos para %s: %s", req.name, exc)
        raise HTTPException(status_code=422, detail="argumentos inválidos") from exc
    return {"name": req.name, "result": result}
