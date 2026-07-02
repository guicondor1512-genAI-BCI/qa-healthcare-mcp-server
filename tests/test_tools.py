from app.tools import list_tools, call_tool

def test_lists_tools():
    names = {t["name"] for t in list_tools()}
    assert {"drug_lookup","interaction_check"} <= names

def test_drug_lookup():
    r = call_tool("drug_lookup", {"name":"sertralina"})
    assert r["found"] and r["info"]["classe"] == "ISRS"

def test_interaction():
    r = call_tool("interaction_check", {"drug_a":"sertralina","drug_b":"ibuprofeno"})
    assert r["interaction"] is True
