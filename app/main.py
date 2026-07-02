"""MCP Server (FastAPI) — spec §4, §10.

Endpoints:
  GET  /mcp/tools      -> lista as tools disponíveis (nome, descrição, schema)
  POST /mcp/call       -> invoca uma tool com argumentos
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .tools import call_tool, list_tools

app = FastAPI(title="QA Healthcare — MCP Server", version="0.1.0")


class CallReq(BaseModel):
    name: str
    arguments: dict[str, Any] = {}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "tools": [t["name"] for t in list_tools()]}


@app.get("/mcp/tools")
async def tools() -> dict:
    return {"tools": list_tools()}


@app.post("/mcp/call")
async def call(req: CallReq) -> dict:
    try:
        result = call_tool(req.name, req.arguments)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TypeError as exc:  # argumentos inválidos
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"name": req.name, "result": result}
