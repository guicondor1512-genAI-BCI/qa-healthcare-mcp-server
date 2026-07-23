# qa-healthcare-mcp-server

Microsserviço da plataforma **QA Healthcare** (Agentic RAG + Corrective RAG).
Este repositório contém apenas o serviço `mcp-server`. Para subir a plataforma
completa (todos os serviços juntos), use o repositório de infraestrutura
`qa-healthcare-deploy`.

## Rodar localmente

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Fonte de dados

`drug_lookup` é cliente MCP de um servidor RxNorm (stdio); `interaction_check` usa base
local (RxNorm não oferece checagem de interação). O servidor RxNorm é configurável por
env var (design agnóstico ao servidor):

| Variável | Default (imagem Docker) | Descrição |
|---|---|---|
| `RXNORM_MCP_COMMAND` | `python` | comando do servidor MCP RxNorm |
| `RXNORM_MCP_ARGS` | `/app/rxnorm_mcp_server.py` | argumentos (separados por espaço) |

A imagem embarca `rxnorm_mcp_server.py`, um servidor RxNorm MCP compatível que bate no
RxNav real. Nota: o [medical-mcp](https://github.com/JamesANZ/medical-mcp) da comunidade
**não** funciona por stdio (imprime banner no stdout e quebra o handshake JSON-RPC) — ver
`docs/rxnorm-mcp-migration.md` §5.5.

## Docker

```bash
docker compose up -d --build      # publica em http://localhost:8010
```

Ou sem compose:

```bash
docker build -t qa-healthcare-mcp-server .
docker run -p 8010:8000 qa-healthcare-mcp-server
```

## Testes

```bash
pip install -r requirements.txt pytest pytest-asyncio
pytest -q
```
