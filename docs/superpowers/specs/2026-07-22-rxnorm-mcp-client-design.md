# Design — Trocar o MCP interno (dicionários) pelo MCP RxNorm externo

Data: 2026-07-22
Serviço: `qa-healthcare-mcp-server`

## Objetivo

Substituir a base de dados local do `drug_lookup` (dicionário `_DRUGS`) por consultas
a um servidor MCP RxNorm externo da comunidade (`medical-mcp`, Node/stdio), fazendo o
microserviço agir como **cliente MCP**. A tool `interaction_check` permanece local
(dicionário `_INTERACTIONS`), pois o RxNorm/RxNav não oferece checagem de interação
(a API de interações da NLM foi descontinuada em 2024).

## Decisões (alinhadas com o usuário)

- Fonte: servidor MCP RxNorm externo da comunidade — `medical-mcp` (JamesANZ).
- Transporte: stdio (subprocesso Node), via SDK oficial `mcp` do Python.
- `interaction_check`: mantém dicionário local, sem alteração.
- Schema de resposta de topo (`found/status/drug/info`) preservado; conteúdo de `info` muda.

## Arquitetura

O `mcp-server` passa de puramente local para **cliente MCP** de um servidor RxNorm externo.

- Nova dependência: SDK `mcp` (Python) no `requirements.txt`; `medical-mcp` disponível
  como comando Node (via `npx -y medical-mcp` ou caminho configurado).
- Config por env var:
  - `RXNORM_MCP_COMMAND` (default `npx`)
  - `RXNORM_MCP_ARGS` (default `-y medical-mcp`, separado por espaços)
- Ciclo de vida: por request, o handler abre uma sessão stdio (`stdio_client` →
  `ClientSession`), chama a tool, e fecha. Sem estado compartilhado nem concorrência.
  Custo aceito: cold start do Node por chamada (demo). Circuit breaker/timeout são
  responsabilidade do orquestrador, conforme comentário já existente em `tools.py`.
- `drug_lookup` vira `async` (chama rede); `interaction_check` continua síncrono e local.

## Contrato da tool externa

Tool: `search-drug-nomenclature`
- Input: `{ "query": <nome> }`
- Por baixo: RxNav `GET /drugs.json?name=<nome>`; retorna conceitos RxNorm com campos
  `rxcui, name, tty, language, synonym`.
- Retorno MCP: **texto formatado** (lista markdown numerada), não JSON. Exemplo:
  ```
  1. **sertraline**
     RxCUI: 36437
     Term Type: IN
     Synonyms: Zoloft, ...
  ```

## Mapeamento de `drug_lookup(name)`

1. Abre sessão stdio → chama `search-drug-nomenclature` com `{query: name}`.
2. `found` = o texto lista >= 1 conceito (heurística: contém `RxCUI:`); senão `unknown_drug`.
3. Extrai do primeiro conceito, via regex leve, `rxcui` e `name` normalizado; mantém texto bruto.

Resposta (topo inalterado; `info` reflete o RxNorm real):
```json
{
  "found": true,
  "status": "found",
  "drug": "sertralina",
  "info": {
    "rxcui": "36437",
    "normalized_name": "sertraline",
    "rxnorm_text": "<texto bruto da tool>"
  }
}
```
Consequência: quem lia `info["classe"]` deixa de encontrar — RxNorm não fornece
classe/dose/indicação nesse endpoint. Estrutura de topo mantida, então o orquestrador
não quebra no contrato.

## Estrutura de código

Novo módulo `app/rxnorm_client.py` (seam de rede isolado):
```python
async def normalize_drug(name: str) -> str:
    # abre stdio_client(ClientSession) com o comando do env,
    # chama search-drug-nomenclature, retorna o texto do content.
```

`app/tools.py`:
- `tool_drug_lookup` vira `async`; chama `rxnorm_client.normalize_drug` + parsing.
- `tool_interaction_check` inalterada.
- `call_tool` vira `async` (precisa `await` no handler async); validador de argumentos inalterado.

`app/main.py`:
- `result = await call_tool(...)`.

`requirements.txt`: adiciona `mcp`.

## Tratamento de erro

- Tool não encontrada / argumentos inválidos: mesmo comportamento atual (404 / 422).
- Falha ao falar com o servidor RxNorm (subprocesso/rede): erro propaga como 5xx do
  serviço; o circuit breaker/timeout do orquestrador cobre resiliência. Sem
  programação defensiva extra dentro do mcp-server.

## Testes

- `interaction_check`: todos os testes atuais permanecem passando, sem mudança.
- `drug_lookup`: testes que checavam `info["classe"] == "ISRS"` são **reescritos** para
  mockar `rxnorm_client.normalize_drug` (monkeypatch) com texto RxNorm canônico, e
  afirmar o parsing (`rxcui`, `normalized_name`, `found`/`unknown_drug`). Determinístico,
  sem rede/Node.
- Opcional: 1 teste de integração real marcado `@pytest.mark.integration` (skippável),
  que sobe o `medical-mcp` de verdade.

## Fora de escopo (YAGNI)

- Sessão MCP persistente / pool de conexões.
- Reconexão automática, retries, cache de resultados.
- Enriquecer `info` com classe (RxClass) ou dose/indicação (FDA).
