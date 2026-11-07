"""Вариант B — сервисы DeepArch в общем RAG-индексе: чанки из карточек/требований/
артефактов, поиск retrieve() по данным платформы, цитаты в карточку сервиса,
инвалидация индекса при изменении данных, дедупликация цитат чип+чанк."""
from app import kb
from app.db import exec, now, q1


def _no_llm(monkeypatch):
    monkeypatch.setattr(kb.llm, "configured", lambda: False)


def _svc(client, H, code, name):
    return client.post("/api/services", headers=H,
                       json={"code": code, "name": name, "project_type": "mvp"}).json()["id"]


def test_deeparch_chunks_built_from_db(client, auth):
    A = auth["admin"]
    sid = _svc(client, A, "RAGB1", "Индексный сервис")
    exec("UPDATE artifacts SET content_md=? WHERE service_id=? AND kind='api'",
         ("API принимает JWT, отдаёт выплаты по заявке.", sid))
    client.post(f"/api/services/{sid}/requirements", headers=A,
                json={"text": "PII получателей маскируется в логах", "req_type": "nonfunc"})
    chunks = kb._deeparch_chunks()
    mine = [c for c in chunks if c["page_id"] == f"deeparch-{sid}"]
    assert mine, "чанк сервиса должен попасть в индекс"
    all_text = "\n".join(c["chunk"] for c in mine)
    assert "RAGB1" in all_text and "PII получателей маскируется" in all_text
    assert all(c["url"] == f"#/service/{sid}/card" for c in mine)
    # чанк архитектуры появился из заполненного артефакта
    assert any("выплаты по заявке" in c["chunk"] for c in mine)


def test_retrieve_finds_service_by_content(client, auth):
    sid = _svc(client, auth["admin"], "RAGB2", "Шлюз уведомлений")
    client.post(f"/api/services/{sid}/requirements", headers=auth["admin"],
                json={"text": "Ретрай отправки писем с экспоненциальной задержкой",
                      "req_type": "nonfunc"})
    hits = kb.retrieve("как устроен ретрай отправки писем с задержкой?")
    assert any(h["page_id"] == f"deeparch-{sid}" for h in hits), \
        "retrieve должен находить сервис по содержимому требований"


def test_answer_cites_service_card_without_chip(client, auth, monkeypatch):
    _no_llm(monkeypatch)
    sid = _svc(client, auth["admin"], "RAGB3", "Антифрод-скоринг")
    client.post(f"/api/services/{sid}/requirements", headers=auth["admin"],
                json={"text": "Скоринговая модель пересчитывается ежечасно",
                      "req_type": "func"})
    r = client.post("/api/assistant", headers=auth["admin"],
                    json={"question": "как часто пересчитывается скоринговая модель?"}).json()
    assert r["provider"] == "local-rag"
    assert any(c["page_id"] == f"deeparch-{sid}" and c["url"] == f"#/service/{sid}/card"
               for c in r["citations"]), "цитата на карточку сервиса обязательна"
    assert "RAGB3" in r["answer"] or "скоринг" in r["answer"].lower()


def test_index_invalidated_by_checklist_and_deletion(client, auth):
    A = auth["admin"]
    sid = _svc(client, A, "INVLD", "Инвалидатор")
    client.post(f"/api/services/{sid}/requirements", headers=A,
                json={"text": "Уникальный маркер инвалидации ретрай", "req_type": "func"})
    kb.retrieve("маркер инвалидации")            # строим индекс до изменений
    key_before = kb._da_key()
    exec("INSERT INTO checklist_runs(service_id,answers,score_pct,mandatory_missing,"
         "created_by,created_at) VALUES(?,?,?,?,?,?)",
         (sid, "[]", 77.0, 0, "admin", now()))
    assert kb._da_key() != key_before, "прогон self-check должен инвалицировать индекс"
    text = "\n".join(c["chunk"] for c in kb._deeparch_chunks()
                     if c["page_id"] == f"deeparch-{sid}")
    assert "77.0" in text, "после перестройки чанк содержит свежий self-check"
    rid = q1("SELECT id FROM requirements WHERE service_id=?", (sid,))["id"]
    exec("DELETE FROM requirements WHERE id=?", (rid,))
    assert kb._da_key() != key_before, "удаление требования должно инвалицировать индекс"


def test_citations_deduped_chip_and_chunk(client, auth, monkeypatch):
    """Сервис упомянут в вопросе (чип) И его чанк найден retrieve — одна цитата, не две."""
    _no_llm(monkeypatch)
    sid = _svc(client, auth["admin"], "DDUP1", "Дедупликатор")
    client.post(f"/api/services/{sid}/requirements", headers=auth["admin"],
                json={"text": "Ретрай запросов с экспоненциальной задержкой",
                      "req_type": "nonfunc"})
    r = client.post("/api/assistant", headers=auth["admin"],
                    json={"question": "DDUP1 Дедупликатор: как устроен ретрай с задержкой?"
                      }).json()
    ids = [c["page_id"] for c in r["citations"]]
    assert ids.count(f"deeparch-{sid}") == 1
