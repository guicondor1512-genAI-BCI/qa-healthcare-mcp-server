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

`drug_lookup` é cliente MCP de um servidor RxNorm externo
([medical-mcp](https://github.com/JamesANZ/medical-mcp), Node/stdio); `interaction_check`
usa base local (RxNorm não oferece checagem de interação). Requer Node disponível.
Configurável por env var:

| Variável | Default | Descrição |
|---|---|---|
| `RXNORM_MCP_COMMAND` | `npx` | comando do servidor MCP RxNorm |
| `RXNORM_MCP_ARGS` | `-y medical-mcp` | argumentos (separados por espaço) |

## Docker

```bash
docker build -t qa-healthcare-mcp-server .
docker run -p 8010:8000 qa-healthcare-mcp-server
```

## Testes

```bash
pip install -r requirements.txt pytest pytest-asyncio
pytest -q
```
