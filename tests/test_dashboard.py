"""Регрессия переработанного GET /dashboard (R1-R6): контракт, права, агрегаты."""
from app.db import exec, now


def _readiness(d, sid):
    return next(x for x in d["readiness"] if x["id"] == sid)


def test_authz(client):
    assert client.get("/api/dashboard").status_code == 401


def test_old_contract_preserved(client, auth):
    d = client.get("/api/dashboard", headers=auth["admin"]).json()
    old_keys = {"total_services", "by_review_status", "recent", "component_usage", "standard_ref"}
    assert old_keys <= set(d)
    assert isinstance(d["recent"], list)
    if d["recent"]:
        assert {"id", "code", "name", "review_status", "score"} <= set(d["recent"][0])


def test_readiness_covers_registry(client, auth):
    d = client.get("/api/dashboard", headers=auth["admin"]).json()
    n_svcs = client.get("/api/services", headers=auth["admin"]).json()
    assert len(d["readiness"]) == len(n_svcs)
    need = {"id", "code", "name", "review_status", "mandatory_total", "mandatory_missing",
            "self_check", "fitness", "debts_open", "debts_p0", "debts_p1", "hint"}
    assert need <= set(d["readiness"][0])


def test_readiness_lifecycle_mvp(client, auth):
    """Новый mvp-сервис: артефакты → self-check → подсказки проходят через реальный API."""
    A = auth["admin"]
    svc = client.post("/api/services", headers=A, json={"code": "DASH1", "name": "Тест дашборда",
                                                        "project_type": "mvp"}).json()
    d = client.get("/api/dashboard", headers=A).json()
    r1 = next(x for x in d["readiness"] if x["id"] == svc["id"])
    assert r1["mandatory_missing"]
    assert r1["hint"].startswith("Заполнить")

    for kind in ["vision_c4", "api", "data_model", "config_build"]:
        assert client.put(f"/api/services/{svc['id']}/artifacts/{kind}", headers=A,
                          json={"content_md": f"# {kind}\nСодержимое для проверки дашборда."}
                          ).status_code == 200
    std = client.get("/api/standard", headers=A).json()
    answers = [{"item_id": c["id"], "grade": "E", "link": "https://confluence.dats.tech/dashboard-check"}
               for c in std["checklist"]]
    rc = client.post(f"/api/services/{svc['id']}/checklist", headers=A, json={"answers": answers})
    assert rc.status_code == 200, rc.text
    r2 = next(x for x in client.get("/api/dashboard", headers=A).json()["readiness"]
              if x["id"] == svc["id"])
    assert not r2["mandatory_missing"]
    assert r2["self_check"] is not None and r2["self_check"] > 0
    assert r2["hint"] == "Готов к запросу ревью"


def test_my_tasks_permissions(client, auth):
    A, V, L = auth["admin"], auth["viewer"], auth["lead"]
    dash1 = next(s for s in client.get("/api/services", headers=A).json() if s["code"] == "DASH1")
    rv = client.post(f"/api/services/{dash1['id']}/reviews", headers=A, json={"comment": "прошу ревью"})
    assert rv.status_code == 200, rv.text
    d2 = client.get("/api/dashboard", headers=A).json()
    assert any(p["service_id"] == dash1["id"] for p in d2["my_tasks"]["pending_reviews"])
    # без права review.decide ожидающие ревью не показываются
    assert client.get("/api/dashboard", headers=V).json()["my_tasks"]["pending_reviews"] == []
    assert client.get("/api/dashboard", headers=L).json()["my_tasks"]["pending_reviews"] == []


def test_debts_aggregates(client, auth):
    A = auth["admin"]
    sid = next(s for s in client.get("/api/services", headers=A).json() if s["code"] == "DASH1")["id"]
    exec("INSERT INTO tech_debts(debt_id,dtype,service_id,title,risk,priority,status,created_by,created_at) "
         "VALUES(?,?,?,?,?,?,?,?,?)",
         ("TD-DASH-001", "TD", sid, "Критичный долг для дашборда", "Critical", "P0", "new", "admin", now()))
    exec("INSERT INTO tech_debts(debt_id,dtype,service_id,title,risk,priority,status,created_by,created_at) "
         "VALUES(?,?,?,?,?,?,?,?,?)",
         ("TD-DASH-002", "TD", sid, "Погашенный долг — не должен считаться", "High", "P1", "repaid", "admin", now()))
    d3 = client.get("/api/dashboard", headers=A).json()
    r3 = next(x for x in d3["readiness"] if x["id"] == sid)
    assert r3["debts_p0"] == 1 and r3["debts_open"] == 1
    assert any(t["debt_id"] == "TD-DASH-001" for t in d3["debt_top"])
    assert not any(t["debt_id"] == "TD-DASH-002" for t in d3["debt_top"])
    assert any(x["priority"] == "P0" and x["n"] >= 1 for x in d3["debt_by_priority"])
    assert any(b["id"] == sid and any("P0" in w for w in b["why"]) for b in d3["my_tasks"]["blockers"])


def test_fitness_in_readiness_and_blockers(client, auth):
    A = auth["admin"]
    sid = next(s for s in client.get("/api/services", headers=A).json() if s["code"] == "DASH1")["id"]
    exec("INSERT INTO fitness_runs(service_id,results,passed,failed,warned,created_by,created_at) "
         "VALUES(?,?,?,?,?,?,?)",
         (sid, '[{"rule_id":"r1","name":"проверка","verdict":"fail","detail":"x"}]', 0, 2, 1, "admin", now()))
    d4 = client.get("/api/dashboard", headers=A).json()
    r4 = next(x for x in d4["readiness"] if x["id"] == sid)
    assert r4["fitness"] == {"failed": 2, "warned": 1}
    assert "фитнес" in r4["hint"].lower()
    assert any(b["id"] == sid and any("фитнес" in w for w in b["why"]) for b in d4["my_tasks"]["blockers"])


def test_coverage_counts(client, auth):
    """Свежий сервис без требований/C4/self-check виден во всех трёх срезах покрытия."""
    A = auth["admin"]
    svc = client.post("/api/services", headers=A, json={"code": "DASH2", "name": "Покрытие",
                                                        "project_type": "landing"}).json()
    assert svc["id"], svc
    cov = client.get("/api/dashboard", headers=A).json()["coverage"]
    for key in ("no_requirements", "no_c4", "no_checklist"):
        assert any(x["code"] == "DASH2" for x in cov[key]), {key: [x["code"] for x in cov[key]]}


def test_activity_by_permission(client, auth):
    assert len(client.get("/api/dashboard", headers=auth["admin"]).json()["activity"]) > 0
    assert client.get("/api/dashboard", headers=auth["viewer"]).json()["activity"] == []


def test_readiness_sorting(client, auth):
    """Сервисы с незакрытыми обязательными артефактами — сверху."""
    r9 = client.get("/api/dashboard", headers=auth["admin"]).json()["readiness"]
    missing_lens = [len(x["mandatory_missing"]) for x in r9]
    assert missing_lens == sorted(missing_lens, reverse=True)
