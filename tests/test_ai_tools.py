"""Вариант C — tool-use ассистента: агентный цикл (search_services/get_architecture),
стриминг с tool_use-событиями и откат на запрос без tools, если прокси их не принимает.
llm.chat_tools / chat_stream_tools замоканы — тестируется логика цикла, не сеть."""
import json

from app import kb
from app import llm as llmmod
from app.llm import LLMError


def _svc(client, A, code, name):
    return client.post("/api/services", headers=A,
                       json={"code": code, "name": name, "project_type": "mvp"}).json()["id"]


def test_agent_loop_calls_get_architecture(client, auth, monkeypatch):
    A = auth["admin"]
    sid = _svc(client, A, "TOOL1", "Тулик")
    seen_tool_results = []

    def chat_tools(msgs, tools, **kw):
        last = msgs[-1]
        if last.get("role") == "tool":                      # второй раунд: результат уже в истории
            seen_tool_results.append(last["content"])
            return {"content": "Ответ по данным инструмента.", "tool_calls": []}
        return {"content": "", "tool_calls": [
            {"id": "c1", "name": "get_architecture", "arguments": f'{{"service_id": {sid}}}'},
            {"id": "c2", "name": "search_services", "arguments": '{"query": "тулик"}'}]}

    monkeypatch.setattr(kb.llm, "configured", lambda: True)
    monkeypatch.setattr(kb.llm, "chat_tools", chat_tools)
    monkeypatch.setattr(kb.llm, "config", lambda: ("http://x", "t", "m1"))
    r = kb.answer("расскажи про Тулик", user=None)
    assert r["provider"] == "ai-buddy" and r["answer"] == "Ответ по данным инструмента."
    assert [t["name"] for t in r["tools"]] == ["get_architecture", "search_services"]
    # результат инструмента вернулся модели: карточка сервиса + поиск по имени
    assert any("Тулик" in s and "TOOL1" in s for s in seen_tool_results)
    assert any('"total_matched"' in s for s in seen_tool_results)
    # в истории диалога есть tool-сообщения с корректным tool_call_id
    assert any('"error"' not in s for s in seen_tool_results)


def test_fallback_without_tools_on_http_4xx(client, auth, monkeypatch):
    def chat_tools(msgs, tools, **kw):
        raise LLMError("HTTP 400: tools are not supported by this proxy", status_code=400)

    chat_calls = []
    monkeypatch.setattr(kb.llm, "configured", lambda: True)
    monkeypatch.setattr(kb.llm, "chat_tools", chat_tools)
    monkeypatch.setattr(kb.llm, "chat", lambda msgs, **kw: (chat_calls.append(msgs), "Ответ без tools")[1])
    monkeypatch.setattr(kb.llm, "config", lambda: ("http://x", "t", "m1"))
    r = kb.answer("вопрос")
    assert r["provider"] == "ai-buddy" and r["answer"] == "Ответ без tools"
    assert "tools" not in r
    assert chat_calls and all("tools" not in json.dumps(m) for m in chat_calls[0])


def test_network_error_falls_to_extractive(client, auth, monkeypatch):
    def chat_tools(msgs, tools, **kw):
        raise LLMError("AI-Buddy недоступен: ConnectError")

    monkeypatch.setattr(kb.llm, "configured", lambda: True)
    monkeypatch.setattr(kb.llm, "chat_tools", chat_tools)
    monkeypatch.setattr(kb.llm, "config", lambda: ("http://x", "t", "m1"))
    r = kb.answer("requirements и архитектурные артефакты")   # вопрос с KB-хитами
    assert r["provider"] == "local-rag" and "LLM недоступна" in r["answer"]


def test_stream_emits_tool_use_events(client, auth, monkeypatch):
    A = auth["admin"]
    _svc(client, A, "TOOL2", "Стример")

    def chat_stream_tools(msgs, tools, **kw):
        if msgs[-1].get("role") != "tool":
            yield {"type": "delta", "text": "Смотрю в реестре… "}
            yield {"type": "tool_calls", "tool_calls": [
                {"id": "c1", "name": "search_services", "arguments": '{"query": "стример"}'}]}
            return
        yield {"type": "delta", "text": "Нашёл. Вот ответ."}

    monkeypatch.setattr(kb.llm, "configured", lambda: True)
    monkeypatch.setattr(kb.llm, "chat_stream_tools", chat_stream_tools)
    monkeypatch.setattr(kb.llm, "config", lambda: ("http://x", "t", "m1"))
    evs = list(kb.answer_stream("что такое Стример?"))
    types = [e["type"] for e in evs]
    assert types[0] == "meta" and types[-1] == "done"
    assert "tool_use" in types
    tu = next(e for e in evs if e["type"] == "tool_use")
    assert tu["tools"][0]["name"] == "search_services"
    assert tu["tools"][0]["arguments"] == {"query": "стример"}   # arguments распарсены
    assert "".join(e["text"] for e in evs if e["type"] == "delta") \
        == "Смотрю в реестре… Нашёл. Вот ответ."


def test_tool_executors(client, auth):
    A = auth["admin"]
    sid = _svc(client, A, "TOOL3", "Исполнитель")
    out = json.loads(kb._run_tool("search_services", '{"query": "исполнитель"}'))
    assert out["total_matched"] >= 1 and any(s["code"] == "TOOL3" for s in out["services"])
    assert out["services"][0]["id"] == sid
    arch = kb._run_tool("get_architecture", f'{{"service_id": "{sid}"}}')   # id строкой — ок
    assert "Исполнитель" in arch and "TOOL3" in arch
    assert json.loads(kb._run_tool("get_architecture", '{"service_id": 999999}'))["error"]
    assert "неизвестный инструмент" in kb._run_tool("rm_rf", "{}")
    assert json.loads(kb._run_tool("search_services", "{битый json"))["total_matched"] >= 1  # битые args → {}


def test_tool_rounds_capped(client, auth, monkeypatch):
    monkeypatch.setattr(kb, "MAX_TOOL_ROUNDS", 0)
    monkeypatch.setattr(kb.llm, "configured", lambda: True)
    monkeypatch.setattr(kb.llm, "chat_tools",
                        lambda msgs, tools, **kw: {"content": "", "tool_calls": [
                            {"id": "c", "name": "search_services", "arguments": "{}"}]})
    monkeypatch.setattr(kb.llm, "config", lambda: ("http://x", "t", "m1"))
    r = client.post("/api/assistant", headers=auth["admin"],
                    json={"question": "зюйдвестка флибустьер шхера"}).json()
    assert r["provider"] == "local-rag"   # пустой финальный ответ → извлекающий fallback


def test_tool_delta_accumulation():
    """Разорванные дельты tool_calls накапливаются по index; фолбэки без index/id."""
    acc = {}
    llmmod._accumulate_tool_delta(acc, {"tool_calls": [
        {"index": 0, "id": "a", "function": {"name": "search_services",
                                             "arguments": '{"query"'}}]})
    llmmod._accumulate_tool_delta(acc, {"tool_calls": [
        {"index": 0, "function": {"arguments": ': "мост"}'}}]})
    llmmod._accumulate_tool_delta(acc, {"tool_calls": [
        {"index": 1, "id": "b", "function": {"name": "get_architecture",
                                             "arguments": '{"service_id": 3}'}}]})
    assert acc[0] == {"id": "a", "name": "search_services", "arguments": '{"query": "мост"}'}
    assert acc[1]["name"] == "get_architecture"
    # шлюз без index: каждая запись с именем открывает новый слот
    acc2 = {}
    llmmod._accumulate_tool_delta(acc2, {"tool_calls": [
        {"id": "x", "function": {"name": "f", "arguments": "{}"}}]})
    llmmod._accumulate_tool_delta(acc2, {"tool_calls": [
        {"id": "y", "function": {"name": "g", "arguments": "{}"}}]})
    assert len(acc2) == 2 and acc2[1]["name"] == "g"
    # дельта без tool_calls не меняет аккумулятор
    assert llmmod._accumulate_tool_delta(acc, {"content": "привет"}) == acc
