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
