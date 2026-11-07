"""Регрессия C4-эндпоинтов (гейт B): авторизация, полный цикл, нормализация, экспорт.

Сервис GATE создаётся один раз на модуль и мутирует тестами последовательно —
как в исходном гейт-скрипте.
"""
import json
import re

import pytest

L1 = {"nodes": [{"id": "p1", "type": "person", "name": "Клиент", "desc": "", "tech": "", "x": 80, "y": 200},
                {"id": "s1", "type": "system", "name": "Gate C4", "desc": "наш сервис", "tech": "FastAPI", "x": 400, "y": 200},
                {"id": "x1", "type": "external", "name": "PayGate", "desc": "платежи", "tech": "", "x": 700, "y": 200}],
      "edges": [{"id": "e1", "from": "p1", "to": "s1", "label": "оформляет", "tech": "HTTPS"},
                {"id": "e2", "from": "s1", "to": "x1", "label": "платежи", "tech": "HTTPS"}]}
L2 = {"nodes": [{"id": "c1", "type": "container", "name": "API", "desc": "", "tech": "FastAPI", "x": 200, "y": 120},
                {"id": "c2", "type": "db", "name": "БД", "desc": "", "tech": "PostgreSQL", "x": 200, "y": 320}],
      "edges": [{"id": "e1", "from": "c1", "to": "c2", "label": "SQL", "tech": "SQL"}]}


@pytest.fixture(scope="module")
def sid(client, auth):
    r = client.post("/api/services", headers=auth["admin"],
                    json={"code": "GATE", "name": "Gate C4", "domain": "тест", "project_type": "mvp"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_authz_and_validation(client, auth, sid):
    A, V = auth["admin"], auth["viewer"]
    assert client.get(f"/api/services/{sid}/c4").status_code == 401
    assert client.put(f"/api/services/{sid}/c4/context", headers=V,
                      json={"model": {"nodes": [], "edges": []}}).status_code == 403
    assert client.post(f"/api/services/{sid}/c4/context/ai", headers=V, json={}).status_code == 403
    assert client.post(f"/api/services/{sid}/c4/export", headers=V, json={}).status_code == 403
    assert client.post("/api/services/999999/c4/export", headers=A, json={}).status_code == 404
    assert client.put(f"/api/services/{sid}/c4/bogus", headers=A, json={"model": {}}).status_code == 400


def test_full_cycle_save_read_export(client, auth, sid):
    A = auth["admin"]
    assert client.put(f"/api/services/{sid}/c4/context", headers=A, json={"model": L1}).status_code == 200
    assert client.put(f"/api/services/{sid}/c4/container", headers=A, json={"model": L2}).status_code == 200
    got = client.get(f"/api/services/{sid}/c4", headers=A).json()["models"]
    assert len(got["context"]["nodes"]) == 3 and len(got["container"]["nodes"]) == 2
    assert len(got["context"]["edges"]) == 2

    # roundtrip: normalize не дрейфит
    rt = client.put(f"/api/services/{sid}/c4/context", headers=A,
                    json={"model": {"nodes": got["context"]["nodes"],
                                    "edges": got["context"]["edges"]}}).json()["model"]
    assert rt == {"nodes": got["context"]["nodes"], "edges": got["context"]["edges"]}

    # dry_run не пишет в артефакт
    dry = client.post(f"/api/services/{sid}/c4/export", headers=A, json={"dry_run": True}).json()
    assert "C4Context" in dry["code"] and "C4Container" in dry["code"]
    vc4 = next(a for a in client.get(f"/api/services/{sid}", headers=A).json()["artifacts"]
               if a["kind"] == "vision_c4")
    assert (vc4["diagram_code"] or "") == "" and vc4["version"] == 1

    # экспорт записывает исходник
    exp = client.post(f"/api/services/{sid}/c4/export", headers=A, json={}).json()
    after = next(a for a in client.get(f"/api/services/{sid}", headers=A).json()["artifacts"]
                 if a["kind"] == "vision_c4")
    assert exp["ok"] and exp["updated"] and len(after["diagram_code"]) == exp["code_len"]
    assert after["version"] == 2 and after["updated_by"] == "admin"
    assert "C4Context" in after["diagram_code"] and "C4Container" in after["diagram_code"]

    # self-check: пункты 1-2 стандарта завязаны на vision_c4 — исходник после экспорта есть
    std = client.get("/api/standard", headers=A).json()
    c4items = [i for i in std["checklist"] if i.get("artifact") == "vision_c4"]
    assert len(c4items) >= 2 and len(after["diagram_code"]) > 0

    audits = [a["action"] for a in client.get("/api/audit", headers=A).json()[:40]]
    assert {"c4_save", "c4_export"} <= set(audits)

    # AI-структура без настроенного LLM → детерминированный fallback
    ai = client.post(f"/api/services/{sid}/c4/context/ai", headers=A, json={}).json()
    assert ai["provider"] == "fallback" and ai["model_json"]["nodes"]
    assert ai["view"] == "context"


def test_export_empty_models_blocked_then_force(client, auth, sid):
    """Экспорт пустых моделей блокируется валидацией; force осознанно затирает рукописный исходник."""
    A = auth["admin"]
    client.put(f"/api/services/{sid}/c4/context", headers=A, json={"model": {"nodes": [], "edges": []}})
    client.put(f"/api/services/{sid}/c4/container", headers=A, json={"model": {"nodes": [], "edges": []}})
    blocked = client.post(f"/api/services/{sid}/c4/export", headers=A, json={})
    assert blocked.status_code == 409, blocked.text
    assert "обе модели пусты" in blocked.json()["detail"]
    client.post(f"/api/services/{sid}/c4/export", headers=A, json={"force": True})
    after = next(a for a in client.get(f"/api/services/{sid}", headers=A).json()["artifacts"]
                 if a["kind"] == "vision_c4")
    assert (after["diagram_code"] or "") == ""


def test_export_validation_report(client, auth, sid, monkeypatch):
    """dry_run возвращает отчёт валидации; блокеры и предупреждения детерминированы."""
    import app.c4 as c4m
    A = auth["admin"]
    # L1 без нашего сервиса (только external) → блокер; персоны нет → предупреждение
    client.put(f"/api/services/{sid}/c4/context", headers=A, json={"model": {
        "nodes": [{"id": "x1", "type": "external", "name": "PayGate", "x": 1, "y": 1}],
        "edges": []}})
    rep = client.post(f"/api/services/{sid}/c4/export", headers=A, json={"dry_run": True}).json()["validation"]
    assert any("нет нашего сервиса" in b for b in rep["blockers"])
    assert any("нет ни одной персоны" in w for w in rep["warnings"])

    # висячие связи гасятся normalize при сохранении; validate_models защищает и этот случай
    monkeypatch.setattr(c4m, "load", lambda _sid: {
        "context": {"nodes": [{"id": "s1", "type": "system", "name": "Наш сервис", "x": 1, "y": 1}],
                    "edges": [{"id": "e1", "from": "s1", "to": "ghost", "label": "x", "tech": ""}]},
        "container": {"nodes": [], "edges": []}})
    rep2 = c4m.validate_models(sid)
    assert any("несуществующие узлы" in b for b in rep2["blockers"])
    monkeypatch.undo()

    # корректная L1 → блокеров нет; L2 пустая → предупреждение, но экспорт проходит
    client.put(f"/api/services/{sid}/c4/context", headers=A, json={"model": {
        "nodes": [{"id": "p1", "type": "person", "name": "Клиент", "x": 1, "y": 1},
                  {"id": "s1", "type": "system", "name": "Наш сервис", "x": 300, "y": 1}],
        "edges": [{"id": "e1", "from": "p1", "to": "s1", "label": "использует", "tech": "HTTPS"}]}})
    client.put(f"/api/services/{sid}/c4/container", headers=A, json={"model": {"nodes": [], "edges": []}})
    rep = client.post(f"/api/services/{sid}/c4/export", headers=A, json={"dry_run": True}).json()["validation"]
    assert rep["blockers"] == []
    assert any("не нарисованы" in w for w in rep["warnings"])
    ok = client.post(f"/api/services/{sid}/c4/export", headers=A, json={})
    assert ok.status_code == 200 and "validation" in ok.json()


def test_l1_l2_cascade_context(client, auth):
    """Каскад L1→L2: сохранённая L1 попадает в контекст генерации L2; без L1 — пусто."""
    import app.c4 as c4m
    A = auth["admin"]
    sid = client.post("/api/services", headers=A, json={"code": "CASC1", "name": "Каскад",
                                                        "project_type": "mvp"}).json()["id"]
    assert c4m._l1_context(sid) == ""           # L1 ещё не сохранена
    client.put(f"/api/services/{sid}/c4/context", headers=A, json={"model": {
        "nodes": [{"id": "p1", "type": "person", "name": "Клиент", "x": 1, "y": 1},
                  {"id": "s1", "type": "system", "name": "Наш сервис", "x": 300, "y": 1}],
        "edges": [{"id": "e1", "from": "p1", "to": "s1", "label": "оформляет", "tech": "HTTPS"}]}})
    ctx = c4m._l1_context(sid)
    assert "Клиент (person)" in ctx and "Наш сервис (system)" in ctx
    assert "Клиент → Наш сервис (оформляет)" in ctx
    # битый JSON в c4_models не роняет каскад
    from app.db import exec as _exec
    _exec("UPDATE c4_models SET model_json='{битый' WHERE service_id=? AND view='context'", (sid,))
    assert c4m._l1_context(sid) == ""


def test_nan_inf_coordinates(client, auth, sid):
    """NaN/inf координаты не ломают сериализацию и не сохраняются."""
    A = auth["admin"]
    r = client.put(f"/api/services/{sid}/c4/context", headers={**A, "Content-Type": "application/json"},
                   content='{"model":{"nodes":[{"id":"n1","type":"person","name":"A","x":NaN,"y":1e999}],"edges":[]}}')
    assert r.status_code == 200
    g = client.get(f"/api/services/{sid}/c4", headers=A)
    models = json.loads(g.text)["models"]  # ValueError здесь = провал
    n1 = models["context"]["nodes"][0]
    assert n1["x"] == 480 and n1["y"] == 280


def test_node_id_sanitized_not_lost(client, auth, sid):
    A = auth["admin"]
    xss_id = 'p2"><img src=x onerror=window.__xss=1>'
    client.put(f"/api/services/{sid}/c4/container", headers=A,
               json={"model": {"nodes": [{"id": xss_id, "type": "person", "name": "OK", "x": 1, "y": 1}],
                               "edges": []}})
    back = client.get(f"/api/services/{sid}/c4", headers=A).json()["models"]["container"]["nodes"]
    assert back and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", back[0]["id"]) and back[0]["name"] == "OK"
    back2 = client.put(f"/api/services/{sid}/c4/container", headers=A,
                       json={"model": {"nodes": [{"id": "n" * 41, "type": "person", "name": "Длинный",
                                                  "x": 1, "y": 1}], "edges": []}}).json()["model"]
    assert len(back2["nodes"][0]["id"]) <= 40


def test_export_keeps_both_directions_and_escapes(client, auth, sid):
    """Обе направленные связи, переносы строк, уникальные алиасы."""
    A = auth["admin"]
    client.put(f"/api/services/{sid}/c4/context", headers=A, json={"model": {
        "nodes": [{"id": "a", "type": "system", "name": "A", "x": 1, "y": 1},
                  {"id": "b", "type": "external", "name": "B", "x": 300, "y": 1}],
        "edges": [{"id": "e1", "from": "a", "to": "b", "label": "запрос", "tech": "HTTP"},
                  {"id": "e2", "from": "b", "to": "a", "label": "callback", "tech": "HTTP"}]}})
    code = client.post(f"/api/services/{sid}/c4/export", headers=A, json={"dry_run": True}).json()["code"]
    assert code.count("Rel(") == 2

    # перенос строки в описании не разрывает строковый литерал Mermaid (чётное число кавычек в строке)
    client.put(f"/api/services/{sid}/c4/context", headers=A, json={"model": {
        "nodes": [{"id": "a", "type": "system", "name": "A", "desc": "строка1\nстрока2", "x": 1, "y": 1}],
        "edges": []}})
    nl = client.post(f"/api/services/{sid}/c4/export", headers=A, json={"dry_run": True}).json()["code"]
    assert all(line.count('"') % 2 == 0 for line in nl.splitlines()) and "строка1 · строка2" in nl

    # узел без id при коллизии не теряется
    gen = client.put(f"/api/services/{sid}/c4/context", headers=A, json={"model": {
        "nodes": [{"type": "person", "name": "Без id"},
                  {"id": "n1", "type": "system", "name": "Система"}], "edges": []}}).json()["model"]
    assert len(gen["nodes"]) == 2

    # алиасы 'u-1'/'u_1' после санитизации не склеиваются
    client.put(f"/api/services/{sid}/c4/container", headers=A, json={"model": {"nodes": [], "edges": []}})
    client.put(f"/api/services/{sid}/c4/context", headers=A, json={"model": {
        "nodes": [{"id": "u-1", "type": "person", "name": "Разработчик", "x": 1, "y": 1},
                  {"id": "u_1", "type": "system", "name": "Система", "x": 300, "y": 1}],
        "edges": [{"id": "e1", "from": "u-1", "to": "u_1", "label": "l", "tech": ""}]}})
    al = client.post(f"/api/services/{sid}/c4/export", headers=A, json={"dry_run": True}).json()["code"]
    aliases = sorted(set(re.findall(r"^(?:Person|System_Ext|System)\((\w+),", al, re.MULTILINE)))
    assert len(aliases) == 2 and al.count("Rel(") == 1

    # roundtrip: нормализованные id стабильны
    again = client.put(f"/api/services/{sid}/c4/context", headers=A, json={"model": {
        "nodes": [{"id": "u-1", "type": "person", "name": "Разработчик", "x": 1, "y": 1},
                  {"id": "u_1", "type": "system", "name": "Система", "x": 300, "y": 1}],
        "edges": [{"id": "e1", "from": "u-1", "to": "u_1", "label": "l", "tech": ""}]}}).json()["model"]
    assert [n["id"] for n in again["nodes"]] == ["u-1", "u_1"]
