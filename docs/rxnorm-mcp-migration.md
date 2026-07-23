# Migração: MCP interno (dicionários) → MCP RxNorm externo

Documento técnico da troca da base de dados interna do `mcp-server` por um
**cliente MCP de um servidor RxNorm externo** na tool `drug_lookup`.
Cobre antes/depois, detalhes de API, erros encontrados e como foram resolvidos.

- Serviço: `qa-healthcare-mcp-server`
- Branch/PR: `feat/rxnorm-mcp-client`
- Design: [`docs/superpowers/specs/2026-07-22-rxnorm-mcp-client-design.md`](superpowers/specs/2026-07-22-rxnorm-mcp-client-design.md)

---

## 1. Visão geral

| | Antes | Depois |
|---|---|---|
| `drug_lookup` | dicionário local `_DRUGS` | cliente MCP (stdio) do servidor RxNorm externo |
| `interaction_check` | dicionário local `_INTERACTIONS` | **inalterado** (dicionário local) |
| Fonte de fármacos | 4 fármacos hardcoded | RxNorm/RxNav (base completa da NLM) |
| Natureza da tool | função síncrona pura | função `async` (I/O de rede) |
| Dependências | fastapi, uvicorn, pydantic, httpx | + `mcp==1.2.0` (SDK MCP) + Node no host |

Por que `interaction_check` não migrou: o RxNorm/RxNav **não oferece** checagem de
interação — a *Drug Interaction API* da NLM foi **descontinuada em 2024**. Portanto a
checagem de interação permanece numa base local curada.

---

## 2. Antes

### Arquitetura

O serviço resolvia tudo em memória, sem I/O externo. As duas tools liam dois
dicionários no próprio módulo.

```python
_DRUGS = {
    "sertralina": {"classe": "ISRS", "dose_inicial": "50 mg/dia", "indicacao": "..."},
    "fluoxetina": {...}, "ibuprofeno": {...}, "semaglutida": {...},
}

def tool_drug_lookup(name: str) -> dict:
    info = _DRUGS.get(name.strip().lower())
    found = info is not None
    return {"found": found, "status": "found" if found else "unknown_drug",
            "drug": name, "info": info or {}}
```

`call_tool` era síncrono e fazia `handler(**arguments)` direto.

### Contrato de resposta (antes)

```json
{
  "found": true,
  "status": "found",
  "drug": "sertralina",
  "info": { "classe": "ISRS", "dose_inicial": "50 mg/dia", "indicacao": "depressão, ansiedade" }
}
```

Limitação: dados **inventados**, apenas 4 fármacos, sem rastro a uma fonte oficial.

---

## 3. Depois

### Arquitetura

O `mcp-server` passa a ser **cliente MCP**. A camada de rede fica isolada em
`app/rxnorm_client.py`; a `drug_lookup` só orquestra chamada + parsing.

```
POST /mcp/call {name: "drug_lookup", arguments: {name}}
        │
        ▼
 app/main.py  ── await call_tool(...) ──►  app/tools.py
        │                                        │
        │                          await rxnorm_client.normalize_drug(name)
        │                                        │
        │                          stdio_client → ClientSession → initialize
        │                                        │
        │                          call_tool("search-drug-nomenclature", {query})
        │                                        ▼
        │                             servidor MCP RxNorm (Node/stdio)
        │                                        │  RxNav GET /drugs.json?name=
        │                                        ▼
        │                             texto RxNorm (lista de conceitos)
        │                                        │
        └──────────  _parse_rxnorm(texto) → {rxcui, normalized_name, rxnorm_text}
```

### Código

`app/rxnorm_client.py` (novo — seam de rede, sessão por chamada):

```python
_TOOL_NAME = "search-drug-nomenclature"

def _server_params() -> StdioServerParameters:
    command = os.environ.get("RXNORM_MCP_COMMAND", "npx")
    args = shlex.split(os.environ.get("RXNORM_MCP_ARGS", "-y medical-mcp"))
    return StdioServerParameters(command=command, args=args)

async def normalize_drug(name: str) -> str:
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(_TOOL_NAME, {"query": name})
    return "".join(b.text for b in result.content if getattr(b, "type", None) == "text")
```

`app/tools.py` (`drug_lookup` async + parsing; `call_tool` await-aware):

```python
_RXCUI_RE = re.compile(r"RxCUI:\s*(\d+)")
_NAME_RE = re.compile(r"\*\*(.+?)\*\*")

def _parse_rxnorm(text: str) -> dict | None:
    rxcui = _RXCUI_RE.search(text)
    if rxcui is None:
        return None
    name = _NAME_RE.search(text)
    return {"rxcui": rxcui.group(1),
            "normalized_name": name.group(1).strip() if name else "",
            "rxnorm_text": text}

async def tool_drug_lookup(name: str) -> dict:
    text = await rxnorm_client.normalize_drug(name)
    info = _parse_rxnorm(text)
    found = info is not None
    return {"found": found, "status": "found" if found else "unknown_drug",
            "drug": name, "info": info or {}}

async def call_tool(name, arguments) -> dict:
    ...
    result = handler(**arguments)
    if inspect.isawaitable(result):   # drug_lookup é async, interaction_check não
        result = await result
    return result
```

### Contrato de resposta (depois)

O **topo** (`found/status/drug/info`) é preservado — o orquestrador não quebra na
estrutura. O conteúdo de `info` reflete o RxNorm real:

```json
{
  "found": true,
  "status": "found",
  "drug": "sertralina",
  "info": {
    "rxcui": "36437",
    "normalized_name": "sertraline",
    "rxnorm_text": "1. **sertraline**\n   RxCUI: 36437\n   Term Type: IN\n..."
  }
}
```

---

## 4. Detalhes de API

### 4.1 Protocolo MCP (cliente Python, SDK `mcp`)

Handshake stdio usado pelo `rxnorm_client`:

| Passo | Chamada | Papel |
|---|---|---|
| Transporte | `stdio_client(StdioServerParameters(command, args))` | sobe o subprocesso do servidor MCP e abre pipes stdin/stdout |
| Sessão | `ClientSession(read, write)` | camada de protocolo (JSON-RPC MCP) |
| Handshake | `await session.initialize()` | negocia versão/capabilities |
| Invocação | `await session.call_tool(name, arguments)` | executa a tool; retorna `result.content` (lista de blocos) |

`result.content` é uma lista de blocos de conteúdo; blocos de texto têm `type == "text"`
e `.text`. Agregamos os textos.

### 4.2 Tool do servidor RxNorm — `search-drug-nomenclature`

Servidor de referência: [medical-mcp](https://github.com/JamesANZ/medical-mcp) (Node/stdio).

- **Input** (zod): `{ query: string }` — "Drug name to search for in RxNorm database"
- **Retorno MCP**: um bloco `text` com **texto formatado** (lista markdown numerada),
  **não JSON**. Exemplo:

  ```
  Found 2 drugs for "sertralina":

  1. **sertraline**
     RxCUI: 36437
     Term Type: IN
     Synonyms: Zoloft, Lustral

  2. **sertraline hydrochloride**
     RxCUI: 226340
     Term Type: PIN
  ```

Por isso o parsing é textual (regex sobre `**nome**` e `RxCUI: <n>`), e não desserialização.

### 4.3 Fonte por baixo — RxNav (NLM)

O `medical-mcp` chama a API REST pública RxNav:

- **Endpoint**: `GET https://rxnav.nlm.nih.gov/REST/drugs.json?name=<query>`
- **Resposta**: `drugGroup.conceptGroup[].conceptProperties[]`, cada conceito com:

| Campo RxNav | Descrição |
|---|---|
| `rxcui` | identificador único RxNorm do conceito |
| `name` | nome normalizado |
| `tty` | term type (IN = ingredient, PIN, SBD, SCD, ...) |
| `language` | idioma |
| `synonym` | sinônimos/marcas |
| `suppress`, `umlscui` | flags/CUI UMLS |

Sem chave de API. A checagem de interação **não** existe nesse endpoint (nem em nenhum
outro do RxNav atual).

### 4.4 Mapeamento de campos (antes → depois)

| `info` antes | `info` depois | Observação |
|---|---|---|
| `classe` | — | RxNorm não fornece classe nesse endpoint (viria de RxClass) |
| `dose_inicial` | — | não é dado de RxNorm |
| `indicacao` | — | não é dado de RxNorm |
| — | `rxcui` | novo — id oficial RxNorm |
| — | `normalized_name` | novo — nome normalizado |
| — | `rxnorm_text` | novo — texto bruto da tool (auditoria) |

**Impacto a jusante**: consumidores que liam `info["classe"]` deixam de encontrá-lo.

---

## 5. Erros encontrados e como foram resolvidos

### 5.1 (esperado/TDD) `ImportError: cannot import name 'rxnorm_client'`

Primeiro teste (RED) falhou porque o módulo ainda não existia — comportamento correto
do ciclo TDD. Resolvido ao implementar `app/rxnorm_client.py` (fase GREEN).

### 5.2 Conflito de dependência: `starlette` incompatível com `fastapi`

**Sintoma** ao coletar os testes após instalar `mcp` incrementalmente:

```
TypeError: Router.__init__() got an unexpected keyword argument 'on_startup'
```

**Causa raiz (provada):** instalar `mcp==1.2.0` sozinho puxou `starlette 1.3.1`, muito
mais novo que o suportado por `fastapi==0.115.6`. Como a instalação incremental não faz
backtracking entre pacotes já instalados, o `starlette` subiu além do bound do fastapi:

```
$ uv pip show starlette   # Version: 1.3.1   ← incompatível
$ uv pip show fastapi     # Version: 0.115.6
```

**Resolução:** recriar o venv resolvendo **todas** as dependências num único passo, para
o resolver respeitar o bound do fastapi:

```bash
uv venv --clear
uv pip install -r requirements.txt pytest pytest-asyncio   # resolução única
$ uv pip show starlette   # Version: 0.41.3  ← compatível
```

Prevenção: `mcp==1.2.0` fixado no `requirements.txt`; instalar sempre o conjunto junto.

### 5.3 `NameError: name '_DRUGS' is not defined` em `interaction_check`

**Sintoma:** após remover `_DRUGS` (conhecimento de fármacos migrou para o RxNorm),
5 testes de `interaction_check` quebraram:

```
app/tools.py:58: NameError: name '_DRUGS' is not defined
    unknown = [orig for orig, norm in (...) if norm not in _DRUGS]
```

**Causa raiz:** a lógica M12 do `interaction_check` usava `_DRUGS` para decidir se um
fármaco é "conhecido" (só é seguro afirmar "sem interação" quando ambos são conhecidos).
Ao remover `_DRUGS`, essa referência ficou órfã.

**Resolução:** dar ao `interaction_check` uma definição **local e própria** de "conhecido",
derivada da própria base de interações (sem segunda fonte de verdade):

```python
# Fármacos que a base de interação conhece: os que aparecem em algum par.
_KNOWN_DRUGS: frozenset[str] = frozenset().union(*_INTERACTIONS.keys())
...
unknown = [orig for orig, norm in (...) if norm not in _KNOWN_DRUGS]
```

Efeito colateral consciente: um fármaco que o RxNorm conhece mas que não participa de
nenhum par de interação é tratado como desconhecido **pela checagem de interação** — o
que é honesto, pois a base local realmente não tem informação de interação sobre ele.

### 5.4 Testes travando (rede/subprocesso real)

**Sintoma:** a suíte "pendurava" (exit 144 ao ser morta). O teste HTTP `test_http_call_ok`
exercitava `drug_lookup` de verdade e tentava subir `npx medical-mcp`; o teste de
integração real ficava minutos sem retorno.

**Causa raiz:**
1. Testes unitários não devem tocar a rede — precisavam mockar o boundary.
2. O `medical-mcp` real empacota **puppeteer** (dependência pesada), tornando o
   cold-start via `npx` lento; como `call_tool` **não tem timeout** (resiliência é
   responsabilidade do orquestrador, por design), a chamada aguardava indefinidamente.

**Resolução:**
- Unitários: mockar `rxnorm_client.normalize_drug` via `monkeypatch` com um texto RxNorm
  canônico — determinístico e sem rede.
- Integração real: marcada `@pytest.mark.integration` e **skippável** por default,
  só roda com `RXNORM_INTEGRATION=1`.
- Verificação end-to-end do protocolo MCP feita contra um **servidor MCP stdio local**
  (FastMCP em Python, sem puppeteer), provando `initialize → call_tool → parse` sem
  depender do pacote Node pesado:

  ```bash
  RXNORM_INTEGRATION=1 RXNORM_MCP_COMMAND=<python> RXNORM_MCP_ARGS=fake_rxnorm_server.py \
    pytest tests/test_rxnorm.py::test_drug_lookup_real_server
  # 1 passed
  ```

### 5.5 `medical-mcp` quebra o handshake stdio (banner no stdout)

**Sintoma:** no container, `drug_lookup` retornava 500 (`BrokenResourceError`) ou
pendurava >120 s. A chamada REST direta ao RxNav do próprio container funcionava em
< 2 s, isolando o problema no servidor MCP.

**Causa raiz (provada):** ao subir, o `medical-mcp` imprime um banner no **stdout**:

```
🚨 MEDICAL MCP SERVER - SAFETY NOTICE:
...
📊 DYNAMIC DATA SOURCE NOTICE:
```

No transporte MCP **stdio**, o stdout deve conter **apenas** mensagens JSON-RPC. O
banner corrompe o stream, o parser do cliente falha e o `initialize` nunca completa.
(Além disso, o bin `build/index.js` não tem shebang, então `RXNORM_MCP_COMMAND=medical-mcp`
cai no `/bin/sh` — é preciso invocar via `node <path>`.)

**Resolução:** usar um servidor RxNorm MCP **compatível** (`rxnorm_mcp_server.py`,
FastMCP) que mantém o stdout limpo e bate no RxNav real. O design é agnóstico ao
servidor (comando por env var), então a troca é só de configuração:

```
RXNORM_MCP_COMMAND=python
RXNORM_MCP_ARGS=/app/rxnorm_mcp_server.py
```

---

## 6. Estratégia de testes

| Teste | Escopo | Rede? |
|---|---|---|
| `test_drug_lookup_found_maps_rxnorm` | parsing/mapeamento com client mockado | não |
| `test_drug_lookup_unknown_when_no_concepts` | ausência de RxCUI → `unknown_drug` | não |
| `test_http_call_ok` | camada HTTP de `drug_lookup` com client mockado | não |
| `test_interaction_*` | `interaction_check` local (inalterado) | não |
| `test_drug_lookup_real_server` | integração MCP end-to-end (skippável) | sim |

Resultado atual: **14 passed, 1 skipped**.

---

## 7. Configuração

| Variável | Default | Descrição |
|---|---|---|
| `RXNORM_MCP_COMMAND` | `npx` | comando do servidor MCP RxNorm |
| `RXNORM_MCP_ARGS` | `-y medical-mcp` | argumentos (separados por espaço) |

Requer Node disponível no host. Trocar de servidor RxNorm = ajustar as duas env vars,
sem mudança de código (desde que exponha a tool `search-drug-nomenclature`).

---

## 8. Latência: antes vs depois (medido em Docker)

Medição com `docker compose` (12 iterações por cenário). O serviço antigo (dict,
do repo deploy) rodou em `8010`; o novo (rxnorm-mcp) em `8011`.

| Cenário | mediana | avg | min–max |
|---|---|---|---|
| **Antigo** `drug_lookup` (dict) — 8010 | 0.004s | 0.004s | 0.004–0.005s |
| Novo `interaction_check` (local, inalterado) — 8011 | 0.004s | 0.004s | 0.004–0.005s |
| **Novo** `drug_lookup` (rxnorm-mcp real) — 8011 | **1.469s** | 1.498s | 1.416–1.842s |

**Sim, a latência aumentou** — de ~4 ms para ~1.5 s no `drug_lookup` (~370x). Atribuição:

| Componente | mediana |
|---|---|
| Encanamento MCP (spawn do subprocesso + handshake stdio, por chamada) | ~0.151s |
| REST ao RxNav (fonte real, NLM) | ~1.58s |

Conclusões:
- O aumento é **dominado pela rede ao RxNav** (~1.3–1.9 s), que é o custo de usar dados
  reais em vez de um dicionário em memória — não pelo protocolo MCP.
- O overhead do **modelo de cliente MCP** (subprocesso + handshake a cada chamada) é
  pequeno (~150 ms) perto do RxNav, mas não-desprezível.
- `interaction_check` (local) permanece ~4 ms: o serviço em si não ficou mais lento;
  só a tool que passou a fazer I/O de rede real.

Alavancas de otimização:
- **Cache** de RxCUI por nome corta a maior parte do ~1.5 s em nomes repetidos. **Feito** (§8.1).
- **Sessão MCP persistente** (em vez de subprocesso por chamada) eliminaria os ~150 ms,
  mas só no cache miss (~9% do custo de um miss) e ao preço de manter um subprocesso
  vivo com gestão de ciclo de vida/reconexão. **Não vale** a complexidade neste serviço.

### 8.1 Cache de RxCUI (implementado)

Cache em memória por nome normalizado em `rxnorm_client` (RxNorm é praticamente
estático). Medição em Docker:

| Chamada | Latência |
|---|---|
| 1ª (cache **miss** → RxNav) | ~1.7–1.9s |
| 2ª+ (cache **hit**) | **~0.002s** |

O hit volta ao patamar do dict antigo (~2–4 ms). Só o primeiro acesso a cada nome paga
o RxNav; nomes repetidos ficam instantâneos.

> Nota: a medição usou um servidor RxNorm MCP compatível próprio (`rxnorm_mcp_server.py`),
> porque o `medical-mcp` da comunidade **quebra o handshake stdio** ao imprimir um banner
> no stdout (ver §5.5). O overhead de spawn de um servidor Node seria um pouco maior no
> cold-start, mas a conclusão (RxNav domina) não muda.

## 9. Limitações e responsabilidades

- **Sem resiliência local** (timeout/retry/circuit breaker): é responsabilidade do
  orquestrador, conforme o comentário original do serviço.
- **Cold-start**: sessão stdio por chamada (sobe o subprocesso a cada request) — simples
  e sem estado compartilhado, ao custo de latência; adequado ao demo.
- **`info` sem classe/dose/indicação**: RxNorm não os fornece nesse endpoint; enriquecer
  exigiria RxClass (classe) e/ou FDA (dose/indicação) — fora do escopo.
