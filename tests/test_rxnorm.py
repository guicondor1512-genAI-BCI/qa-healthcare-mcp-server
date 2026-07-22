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
