"""Слой 4 — персональный контекст ассистента: роль, мои сервисы (карточка +
product-гранты), группы, назначенные ревью, техдолг на пользователе.
LLM замокана на fallback-ветку (local-rag) — проверяется сборка контекста, не генерация."""
from app import kb
from app.db import exec, now


def _ask(client, H, question, **kw):
    return client.post("/api/assistant", headers=H,
                       json={"question": question, **kw}).json()


def _no_llm(monkeypatch):
    monkeypatch.setattr(kb.llm, "configured", lambda: False)


def test_personal_context_my_services(client, auth, monkeypatch):
    _no_llm(monkeypatch)
    L = auth["lead"]
    client.post("/api/services", headers=L, json={"code": "PERS1", "name": "Персональный",
                                                  "project_type": "mvp"})
    r = _ask(client, L, "зюйдвестка флибустьер шхера")   # ни KB, ни упоминаний сервисов
    assert r["provider"] == "local-rag"
    assert "PERS1" in r["answer"] and "Мои сервисы" in r["answer"]
    assert "роль: team_lead" in r["answer"]


def test_no_personal_context_means_none_answer(client, auth, monkeypatch):
    _no_llm(monkeypatch)
    r = _ask(client, auth["viewer"], "зюйдвестка флибустьер шхера")
    assert r["provider"] == "none" and r["confidence"] == 0.0


def test_my_service_ids_includes_product_grant(client, auth):
    A = auth["admin"]
    sid = client.post("/api/services", headers=A, json={"code": "PGRNT", "name": "Грантовый",
                                                        "project_type": "mvp"}).json()["id"]
    gid = client.post("/api/admin/groups", headers=A,
                      json={"name": "Команда ПерсГрант", "kind": "product"}).json()["id"]
    client.post(f"/api/admin/groups/{gid}/members", headers=A, json={"username": "lead"})
    client.post(f"/api/admin/groups/{gid}/services", headers=A, json={"service_id": sid})
    ids = kb.roles.my_service_ids({"username": "lead", "role": "team_lead"})
    assert sid in ids


def test_personal_reviews_and_debts(client, auth, monkeypatch):
    _no_llm(monkeypatch)
    L = auth["lead"]
    sid = client.post("/api/services", headers=L, json={"code": "PERS2", "name": "Ревью-перс",
                                                        "project_type": "mvp"}).json()["id"]
    exec("INSERT INTO reviews(service_id,requested_by,requested_at,status,comment) "
         "VALUES(?,?,?,?,?)", (sid, "lead", now(), "in_review", ""))
    exec("INSERT INTO tech_debts(debt_id,dtype,service_id,title,priority,status,owner,"
         "created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
         ("TD-PERS", "design", sid, "Проверка персонального техдолга", "high", "open", "lead",
          "lead", now()))
    # ревью ждут решения те, у кого право review.decide (admin), техдолг — владелец (lead)
    r_admin = _ask(client, auth["admin"], "зюйдвестка флибустьер шхера")
    assert "Ревью, ожидающие моего решения" in r_admin["answer"] and "PERS2" in r_admin["answer"]
    r_lead = _ask(client, L, "зюйдвестка флибустьер шхера")
    assert "TD-PERS" in r_lead["answer"] and "Техдолг, за который отвечаю" in r_lead["answer"]


def test_llm_messages_include_personal_block(client, auth, monkeypatch):
    _no_llm(monkeypatch)
    personal = kb._personal_context({"username": "lead", "role": "team_lead",
                                     "display_name": "Лид"})
    assert personal and "роль: team_lead" in personal
    msgs = kb._llm_messages("вопрос", [], None, None, "реестр", personal)
    user_content = msgs[-1]["content"]
    assert user_content.index("Персональный контекст пользователя") \
        < user_content.index("Данные платформы DeepArch")
