"""AI-генерация diagram_code (решение 2026-11-07): AI-черновик deployment/data_model
возвращает и Mermaid-исходник; vision_c4 исключён — его диаграмма производная C4-редактора.
Мок-путь проверяет skeleton-фоллбек, LLM-путь — mocked chat (принятие и отбраковка)."""
from app import ai as aimod


def _draft(client, A, sid, kind, monkeypatch=None, configured=False, chat=None):
    if monkeypatch:
        monkeypatch.setattr(aimod.llm, "configured", lambda: configured)
        if chat is not None:
            monkeypatch.setattr(aimod.llm, "chat", chat)
    return client.post("/api/ai/draft", headers=A, json={"service_id": sid, "kind": kind}).json()


def test_draft_returns_diagram_for_diag_kinds(client, auth, monkeypatch):
    A = auth["admin"]
    sid = client.post("/api/services", headers=A, json={"code": "AIDG", "name": 'Диа"грам{ма}',
                                                        "project_type": "mvp"}).json()["id"]
    # мок-путь изолирован от окружения: LLM не сконфигурирована даже если env задаёт AI-Buddy
    r = _draft(client, A, sid, "deployment", monkeypatch)
    code = r["diagram_code"]
    assert code.lstrip().startswith("C4Deployment")
    assert code.count("{") == code.count("}")           # валидная вложенность
    assert "[TODO]" in code                             # skeleton помечает неизвестное
    assert '"' not in code.split("title")[1].split("\n")[0]   # имя сервиса экранировано (_mq)

    r = _draft(client, A, sid, "data_model", monkeypatch)
    assert r["diagram_code"].lstrip().startswith("erDiagram")

    # у остальных видов диаграмма не генерируется вовсе
    for kind in ("vision_c4", "api", "adr"):
        r = _draft(client, A, sid, kind, monkeypatch)
        assert "diagram_code" not in r, kind


def test_llm_path_accepts_valid_and_falls_back_on_garbage(client, auth, monkeypatch):
    A = auth["admin"]
    sid = client.post("/api/services", headers=A, json={"code": "AILL", "name": "LLM path",
                                                        "project_type": "mvp"}).json()["id"]
    good = "```mermaid\nerDiagram\n  ORDER ||--o{ ITEM : contains\n```"   # с ограждениями — срежутся

    def chat(messages, **kw):
        # вызовы параллельные — маршрут по system-промпту, а не по порядку
        return good if "Mermaid" in messages[0]["content"] else "# черновик контента"

    r = _draft(client, A, sid, "data_model", monkeypatch, configured=True, chat=chat)
    assert r["diagram_code"] == "erDiagram\n  ORDER ||--o{ ITEM : contains"
    assert r["provider"] == "ai-buddy"

    # мусор от LLM (чужой заголовок) → skeleton-фоллбек, черновик всё равно вставлен
    def chat_bad(messages, **kw):
        return "flowchart LR\n  A --> B"

    r = _draft(client, A, sid, "data_model", monkeypatch, configured=True, chat=chat_bad)
    assert r["diagram_code"].lstrip().startswith("erDiagram")
    assert "[TODO]" in r["diagram_code"]
