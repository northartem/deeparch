"""Готовность к ревью: авто-чек из данных DeepArch вместо ручного self-check.

GET /services/{id}/readiness — живой ответ «всё ли есть перед отправкой» (без записи в БД);
POST /services/{id}/reviews — gate по авто-чеку и автоматическая фиксация checklist_run.
Блокируют только обязательные пункты: по весу чек-листа И в рамках матрицы типа проекта.
"""


def _make_service(client, auth, code):
    r = client.post("/api/services", headers=auth["admin"],
                    json={"code": code, "name": f"Сервис {code}", "project_type": "mvp"})
    assert r.status_code == 200, r.text
    return r.json()


def test_readiness_empty_draft_not_ready(client, auth):
    A = auth["admin"]
    sid = _make_service(client, auth, "RDY1")["id"]
    r = client.get(f"/api/services/{sid}/readiness", headers=A)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ready"] is False
    # блокеры = обязательный набор матрицы mvp + карточка; ADR/Deployment (desired) не блокируют
    assert any("Карточка" in b for b in d["blockers"])
    assert any("C4 System Context" in b for b in d["blockers"])
    assert any("API-спецификация" in b for b in d["blockers"])
    assert any("Модель данных" in b for b in d["blockers"])   # в матрице mvp mandatory
    assert any("Config & Build" in b for b in d["blockers"])  # в матрице mvp mandatory
    assert not any("ADR" in b for b in d["blockers"])
    assert not any("Deployment" in b for b in d["blockers"])
    # каждый пункт ведёт внутрь DeepArch (артефакты или карточка)
    assert all(i["link"].startswith("#/service/") for i in d["items"])
    # фабрика создания оставляет пустой чек-ран (answers=[]), readiness его не считает готовностью
    assert d["last_run"] is not None and d["last_run"]["score_pct"] == 0.0


def test_review_blocked_when_not_ready(client, auth):
    A = auth["admin"]
    sid = _make_service(client, auth, "RDY2")["id"]
    runs_before = len(client.get(f"/api/services/{sid}", headers=A).json()["checklist_runs"])
    r = client.post(f"/api/services/{sid}/reviews", headers=A, json={"comment": "рано"})
    assert r.status_code == 409
    assert "Карточка" in r.json()["detail"]
    # blocked attempt не создаёт нового чек-рана
    runs_after = len(client.get(f"/api/services/{sid}", headers=A).json()["checklist_runs"])
    assert runs_after == runs_before


def test_readiness_ready_after_fill_and_auto_run(client, auth):
    A = auth["admin"]
    sid = _make_service(client, auth, "RDY3")["id"]
    r = client.patch(f"/api/services/{sid}", headers=A,
                     json={"owner": "a.larshin", "domain": "Payments"})
    assert r.status_code == 200, r.text
    for kind in ["vision_c4", "api", "data_model", "config_build"]:
        r = client.put(f"/api/services/{sid}/artifacts/{kind}", headers=A,
                       json={"content_md": f"# {kind}\nсодержимое"})
        assert r.status_code == 200, r.text
    d = client.get(f"/api/services/{sid}/readiness", headers=A).json()
    assert d["ready"] is True and d["blockers"] == []
    grades = {i["item_id"]: i["grade"] for i in d["items"]}
    assert grades[10] == "E"          # карточка
    assert grades[3] == "N"           # Deployment для mvp не обязателен — не блокер
    assert not any(i["blocking"] and "ADR" in i["item"] for i in d["items"])  # desired по матрице
    # ручной self-check не проводился — чек-ран появится только при отправке на ревью
    runs_before = len(client.get(f"/api/services/{sid}", headers=A).json()["checklist_runs"])
    r = client.post(f"/api/services/{sid}/reviews", headers=A, json={"comment": "готов"})
    assert r.status_code == 200, r.text
    runs = client.get(f"/api/services/{sid}", headers=A).json()["checklist_runs"]
    assert len(runs) == runs_before + 1       # чек-ран зафиксирован автоматически
    assert runs[0]["score_pct"] > 0           # актуальный скор, не фабричный ноль
    svc = client.get(f"/api/services/{sid}", headers=A).json()
    assert len(svc["last_answers"]) == 10     # авто-ответы сохранены в истории
    # ссылка-доказательство ведёт в DeepArch, а не во внешний Confluence
    assert all(a["link"].startswith("#/service/") for a in svc["last_answers"])
