"""Каталог видов артефактов: консистентность стандарта, scaffolding, новые kind."""
from app.standards import ARTIFACT_KINDS, PROJECT_TYPES


def test_matrix_kinds_present_in_catalog():
    """Все kind из матриц типов проектов существуют в ARTIFACT_KINDS (регрессия threat_model/drp_bcp)."""
    matrix_kinds = {k for pt in PROJECT_TYPES.values() for k in pt["matrix"]}
    catalog = {a["kind"] for a in ARTIFACT_KINDS}
    assert matrix_kinds <= catalog, sorted(matrix_kinds - catalog)
    assert len(catalog) == 9 and {"threat_model", "drp_bcp"} <= catalog


def test_catalog_entries_complete():
    for a in ARTIFACT_KINDS:
        assert a["kind"] and a["title"] and a["question"] and a["template_ref"], a


def test_standard_endpoint_and_critical_scaffold(client, auth):
    A = auth["admin"]
    std = client.get("/api/standard", headers=A).json()
    assert len(std["artifacts"]) == 9
    tm = next(a for a in std["artifacts"] if a["kind"] == "threat_model")
    assert tm["title"] and tm["question"] and tm["template_ref"]

    # scaffolding критического сервиса: 9 артефактов, новые создаются пустыми
    r = client.post("/api/services", headers=A, json={"code": "CRIT1", "name": "Критичный тест",
                                                      "project_type": "critical"})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    svc = client.get(f"/api/services/{sid}", headers=A).json()
    arts = {a["kind"]: a for a in svc["artifacts"]}
    assert len(arts) == 9
    assert (arts["threat_model"]["content_md"] or "") == "" and (arts["drp_bcp"]["content_md"] or "") == ""
    assert {"threat_model", "drp_bcp"} <= set(svc["mandatory_artifacts"])

    # сохранение реального контента в новый вид ДО scaffold
    put = client.put(f"/api/services/{sid}/artifacts/threat_model", headers=A,
                     json={"content_md": "## Threat Model — реальное содержимое"})
    assert put.status_code == 200, put.text

    # dashboard: threat_model заполнен → не в missing; drp_bcp пуст → в missing с человеческим названием
    rd = next(x for x in client.get("/api/dashboard", headers=A).json()["readiness"] if x["id"] == sid)
    miss = {m["kind"] for m in rd["mandatory_missing"]}
    assert rd["mandatory_total"] == 9 and miss == set(svc["mandatory_artifacts"]) - {"threat_model"}
    assert "Threat Model" not in rd["hint"] and "DRP & BCP" in rd["hint"]

    # scaffold: шаблоны для 8 пустых, заполненный threat_model не трогает, идемпотентен
    sc = client.post(f"/api/services/{sid}/artifacts/scaffold", headers=A)
    assert sc.status_code == 200, sc.text
    created = set(sc.json()["created"])
    assert created == set(svc["mandatory_artifacts"]) - {"threat_model"}
    got = {a["kind"]: a for a in client.get(f"/api/services/{sid}", headers=A).json()["artifacts"]}
    assert (got["drp_bcp"]["content_md"] or "").strip().startswith("## DRP & BCP")
    assert got["threat_model"]["content_md"].endswith("содержимое")
    assert client.post(f"/api/services/{sid}/artifacts/scaffold", headers=A).json()["created"] == []

    # AI-черновик для нового вида не падает
    ai = client.post("/api/ai/draft", headers=A, json={"service_id": sid, "kind": "threat_model"})
    assert ai.status_code == 200, ai.text
