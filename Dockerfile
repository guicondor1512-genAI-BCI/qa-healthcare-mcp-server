FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# Servidor MCP RxNorm (stdio) consumido pela tool drug_lookup. Usamos um servidor
# compativel proprio: o medical-mcp da comunidade polui o stdout com um banner e
# quebra o handshake stdio do MCP (stdout deve ser so JSON-RPC).
COPY rxnorm_mcp_server.py .
ENV RXNORM_MCP_COMMAND=python \
    RXNORM_MCP_ARGS=/app/rxnorm_mcp_server.py
# Porta do container; o compose/README publica externamente como 8010:8000.
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
