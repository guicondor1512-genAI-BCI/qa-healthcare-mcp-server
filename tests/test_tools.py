import pytest
from fastapi.testclient import TestClient

from app import rxnorm_client
from app.main import app
from app.tools import call_tool, list_tools

client = TestClient(app)

_RXNORM_TEXT = "1. **sertraline**\n   RxCUI: 36437\n   Term Type: IN\n"


@pytest.fixture
def mock_normalize(monkeypatch):
    async def _fake(name):
        return _RXNORM_TEXT
    monkeypatch.setattr(rxnorm_client, "normalize_drug", _fake)


# ---- Tools puras ----

def test_lists_tools():
    names = {t["name"] for t in list_tools()}
    assert {"drug_lookup", "interaction_check"} <= names


async def test_interaction():
    r = await call_tool("interaction_check", {"drug_a": "sertralina", "drug_b": "ibuprofeno"})
    assert r["interaction"] is True
    assert r["status"] == "interaction"


# ---- M12: medicamento desconhecido/erro de digitação != par seguro ----

async def test_interaction_unknown_drug_not_safe():
    r = await call_tool("interaction_check", {"drug_a": "aspirinaXX", "drug_b": "naoexiste"})
    # NÃO deve implicar segurança: interaction False está reservado para pares conhecidos.
    assert r["interaction"] is None
    assert r["status"] == "unknown_drug"
    assert "aspirinaXX" in r["unknown_drug"] and "naoexiste" in r["unknown_drug"]
    # Distinto da mensagem tranquilizadora de par seguro.
    assert r["note"] != "Sem interação conhecida na base."


async def test_interaction_one_unknown_drug():
    r = await call_tool("interaction_check", {"drug_a": "sertralina", "drug_b": "naoexiste"})
    assert r["status"] == "unknown_drug"
    assert r["interaction"] is None
    assert r["unknown_drug"] == ["naoexiste"]


async def test_interaction_known_safe_pair():
    r = await call_tool("interaction_check", {"drug_a": "fluoxetina", "drug_b": "ibuprofeno"})
    # Ambos conhecidos, sem interação registrada -> False explícito (seguro).
    assert r["interaction"] is False
    assert r["status"] == "no_interaction"
    assert r["note"] == "Sem interação conhecida na base."


# ---- Simetria da chave de interação ----

async def test_interaction_symmetric():
    ab = await call_tool("interaction_check", {"drug_a": "sertralina", "drug_b": "ibuprofeno"})
    ba = await call_tool("interaction_check", {"drug_a": "ibuprofeno", "drug_b": "sertralina"})
    assert ab["interaction"] == ba["interaction"] is True
    assert ab["note"] == ba["note"]


# ---- Camada HTTP (M13/L12/M14) ----

def test_http_call_ok(mock_normalize):
    resp = client.post("/mcp/call", json={"name": "drug_lookup", "arguments": {"name": "sertralina"}})
    assert resp.status_code == 200
    assert resp.json()["result"]["found"] is True


def test_http_unknown_tool_404():
    resp = client.post("/mcp/call", json={"name": "inexistente", "arguments": {}})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "tool desconhecida"


def test_http_bad_type_argument_422_not_500():
    # M13: valor não-string não pode virar 500 (validação antes do handler, sem rede).
    resp = client.post("/mcp/call", json={"name": "drug_lookup", "arguments": {"name": 123}})
    assert resp.status_code == 422
    assert resp.json()["detail"] == "argumentos inválidos"


def test_http_missing_argument_422():
    resp = client.post("/mcp/call", json={"name": "drug_lookup", "arguments": {}})
    assert resp.status_code == 422


def test_http_extra_argument_422():
    resp = client.post(
        "/mcp/call",
        json={"name": "drug_lookup", "arguments": {"name": "sertralina", "foo": 1}},
    )
    assert resp.status_code == 422


def test_http_list_tools():
    resp = client.get("/mcp/tools")
    assert resp.status_code == 200
    names = {t["name"] for t in resp.json()["tools"]}
    assert {"drug_lookup", "interaction_check"} <= names
