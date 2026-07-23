"""Testes do drug_lookup como cliente MCP RxNorm (client mockado)."""
import os

import pytest

from app import rxnorm_client
from app.tools import call_tool

# Texto canonico como o medical-mcp (search-drug-nomenclature) retorna.
_RXNORM_TEXT = (
    "Found 2 drugs for \"sertralina\":\n\n"
    "1. **sertraline**\n"
    "   RxCUI: 36437\n"
    "   Term Type: IN\n"
    "   Synonyms: Zoloft, Lustral\n\n"
    "2. **sertraline hydrochloride**\n"
    "   RxCUI: 226340\n"
    "   Term Type: PIN\n\n"
)

_RXNORM_EMPTY = 'No drugs found for "naoexiste".'


@pytest.fixture
def mock_normalize(monkeypatch):
    def _set(text):
        async def _fake(name):
            return text
        monkeypatch.setattr(rxnorm_client, "normalize_drug", _fake)
    return _set


@pytest.mark.asyncio
async def test_drug_lookup_found_maps_rxnorm(mock_normalize):
    mock_normalize(_RXNORM_TEXT)
    r = await call_tool("drug_lookup", {"name": "sertralina"})
    assert r["found"] is True
    assert r["status"] == "found"
    assert r["drug"] == "sertralina"
    assert r["info"]["rxcui"] == "36437"
    assert r["info"]["normalized_name"] == "sertraline"
    assert "RxCUI: 36437" in r["info"]["rxnorm_text"]


@pytest.mark.asyncio
async def test_drug_lookup_unknown_when_no_concepts(mock_normalize):
    mock_normalize(_RXNORM_EMPTY)
    r = await call_tool("drug_lookup", {"name": "naoexiste"})
    assert r["found"] is False
    assert r["status"] == "unknown_drug"
    assert r["info"] == {}


# ---- Cache de RxCUI (evita refazer o fetch para o mesmo nome) ----

@pytest.mark.asyncio
async def test_normalize_drug_caches_same_name(monkeypatch):
    calls = {"n": 0}

    async def fake_call(name):
        calls["n"] += 1
        return f"1. **{name}**\n   RxCUI: 999\n"

    monkeypatch.setattr(rxnorm_client, "_call_mcp", fake_call)
    rxnorm_client._cache.clear()

    a = await rxnorm_client.normalize_drug("aspirina")
    b = await rxnorm_client.normalize_drug("  Aspirina ")  # mesmo nome normalizado
    assert a == b
    assert calls["n"] == 1  # segunda veio do cache


@pytest.mark.asyncio
async def test_normalize_drug_cache_is_per_name(monkeypatch):
    calls = {"n": 0}

    async def fake_call(name):
        calls["n"] += 1
        return "RxCUI: 1\n"

    monkeypatch.setattr(rxnorm_client, "_call_mcp", fake_call)
    rxnorm_client._cache.clear()

    await rxnorm_client.normalize_drug("a")
    await rxnorm_client.normalize_drug("b")
    assert calls["n"] == 2


# ---- Integração real (skippavel): sobe o medical-mcp de verdade ----

@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("RXNORM_INTEGRATION") != "1",
    reason="define RXNORM_INTEGRATION=1 para rodar contra o medical-mcp real",
)
@pytest.mark.asyncio
async def test_drug_lookup_real_server():
    r = await call_tool("drug_lookup", {"name": "sertraline"})
    assert r["found"] is True
    assert r["info"]["rxcui"].isdigit()
