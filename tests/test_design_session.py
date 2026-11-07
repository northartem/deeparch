"""Design Session (сценарий A): извлечение карточки из документа + живые Next Steps.

Без настроенного LLM извлечение работает через детерминированный fallback —
это и проверяем (реальная БД не открывается, см. conftest).
"""

DOC = """# ТЗ: Платёжный шлюз подписок
Код проекта: SUBGW, домен «Платежи».
Сервис должен обеспечивать оформление и отмену подписок партнёров.
Интеграция с внешним платёжным провайдером по HTTPS.
НФТ: доступность 99,9%, latency p95 < 300 мс, RTO 1 час."""


def test_extract_auth(client):
    assert client.post("/api/ai/service-extract", json={"text": DOC}).status_code == 401


def test_extract_empty(client, auth):
    r = client.post("/api/ai/service-extract", headers=auth["admin"], json={"text": "  "})
    assert r.status_code == 200 and r.json()["provider"] == "none"


def test_extract_fallback_shape(client, auth):
    """Fallback: поля карточки заполнены эвристикой, требования разобраны."""
    r = client.post("/api/ai/service-extract", headers=auth["admin"], json={"text": DOC}).json()
    assert r["provider"] in ("fallback", "ai-buddy")
    d = r["draft"]
    assert d["project_type"] in (None, "mvp", "landing", "critical", "b2c_highload")
    assert d["name"] and "подписок" in d["name"].lower()
    reqs = d["requirements"]
    assert reqs and all({"req_type", "text"} <= set(x) for x in reqs)
    assert all(x["req_type"] in ("func", "nonfunc") for x in reqs)
    # НФТ-маркеры (RTO, p95) распознаются как nonfunc
    assert any(x["req_type"] == "nonfunc" for x in reqs)


def test_design_session_full_flow(client, auth):
    """Сценарий A целиком: extract → scaffold → import reqs → next_steps сужается по ходу работы."""
    A = auth["admin"]
    d = client.post("/api/ai/service-extract", headers=A, json={"text": DOC}).json()["draft"]

    sid = client.post("/api/factory/scaffold", headers=A,
                      json={"code": d["code"] or "SUBGW", "name": d["name"],
                            "domain": d["domain"] or "Платежи",
                            "project_type": d["project_type"] or "mvp"}).json()["id"]
    if d["requirements"]:
        ri = client.post(f"/api/services/{sid}/requirements/import", headers=A,
                         json={"items": d["requirements"], "source_url": "doc:ТЗ SUBGW"})
        assert ri.status_code == 200, ri.text
        imported = ri.json()["created"]
        assert imported and imported[0]["ext_id"].startswith(("ФТ-", "НФТ-"))

    svc = client.get(f"/api/services/{sid}", headers=A).json()
    assert len(svc["requirements"]) == len(d["requirements"])
    # scaffold заполнил шаблоны → шаг «Заполнить артефакты» уже закрыт
    assert not any("Заполнить артефакты" in s for s in svc["next_steps"])
    assert any("self-check" in s for s in svc["next_steps"])
    assert any("C4-модель" in s for s in svc["next_steps"])

    # сохранённая C4-модель закрывает шаг C4
    c4 = client.put(f"/api/services/{sid}/c4/context", headers=A,
                    json={"model": {"nodes": [{"id": "n1", "type": "system", "name": "SUBGW",
                                               "x": 100, "y": 100}], "edges": []}})
    assert c4.status_code == 200, c4.text
    steps = client.get(f"/api/services/{sid}", headers=A).json()["next_steps"]
    assert not any("C4-модель" in s for s in steps)

    # отвеченный self-check закрывает шаг self-check
    std = client.get("/api/standard", headers=A).json()
    answers = [{"item_id": c["id"], "grade": "E", "link": "https://confluence.dats.tech/ds"} for c in std["checklist"]]
    rc = client.post(f"/api/services/{sid}/checklist", headers=A, json={"answers": answers})
    assert rc.status_code == 200, rc.text
    steps = client.get(f"/api/services/{sid}", headers=A).json()["next_steps"]
    assert not any("self-check" in s for s in steps)

    # запрос ревью закрывает последний шаг
    rv = client.post(f"/api/services/{sid}/reviews", headers=A, json={"comment": "прошу ревью"})
    assert rv.status_code == 200, rv.text
    steps = client.get(f"/api/services/{sid}", headers=A).json()["next_steps"]
    assert steps == ["Ожидается решение ревьюера"]


def test_next_steps_done_state(client, auth):
    """Полностью закрытый сервис: одно позитивное сообщение, без пустых шагов."""
    A = auth["admin"]
    svc = client.post("/api/services", headers=A, json={"code": "DS1", "name": "Design Session",
                                                    "project_type": "landing"}).json()
    client.put(f"/api/services/{svc['id']}/artifacts/vision_c4", headers=A, json={"content_md": "x" * 250})
    client.put(f"/api/services/{svc['id']}/artifacts/deployment", headers=A, json={"content_md": "x" * 250})
    client.put(f"/api/services/{svc['id']}/artifacts/config_build", headers=A, json={"content_md": "x" * 250})
    client.put(f"/api/services/{svc['id']}/c4/context", headers=A,
               json={"model": {"nodes": [{"id": "n1", "type": "system", "name": "DS1", "x": 1, "y": 1}],
                               "edges": []}})
    std = client.get("/api/standard", headers=A).json()
    answers = [{"item_id": c["id"], "grade": "E", "link": "https://confluence.dats.tech/ds"} for c in std["checklist"]]
    client.post(f"/api/services/{svc['id']}/checklist", headers=A, json={"answers": answers})
    client.post(f"/api/services/{svc['id']}/reviews", headers=A, json={"comment": "ok"})
    # решение ревью — approve
    rid = client.get(f"/api/services/{svc['id']}", headers=A).json()["reviews"][0]["id"]
    dec = client.post(f"/api/reviews/{rid}/decision", headers=A, json={"verdict": "approved"})
    assert dec.status_code == 200, dec.text
    steps = client.get(f"/api/services/{svc['id']}", headers=A).json()["next_steps"]
    assert len(steps) == 1 and "Готов к ревью" in steps[0]


def test_extract_llm_garbage_falls_back(client, auth, monkeypatch):
    """LLM «настроен», но вернул мусор → тихий переход на fallback, а не 500."""
    import app.ai as aim
    orig_chat, orig_conf = aim.llm.chat, aim.llm.configured
    aim.llm.chat = lambda *a, **k: "не JSON вообще"
    aim.llm.configured = lambda: True
    try:
        r = client.post("/api/ai/service-extract", headers=auth["admin"], json={"text": DOC}).json()
        assert r["provider"] == "fallback" and r["draft"]["requirements"]
    finally:
        aim.llm.chat, aim.llm.configured = orig_chat, orig_conf
