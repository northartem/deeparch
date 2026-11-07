"""AI-ревью до отправки: двухслойный прогон (advisory, BR-33).

Слой 1 (формальный) тестируется без LLM: полнота по матрице типа проекта,
карточка, NFR-цели в цифрах, C4-модели, покрытие требований.
Слой 2 в тестовой среде без AI-Buddy честно помечен «LLM не подключена»
и находок не добавляет. /ai/precheck → 410 (AI Gate поглощён AI-ревью).
"""


def _make_service(client, auth, code, project_type="mvp"):
    r = client.post("/api/services", headers=auth["admin"],
                    json={"code": code, "name": f"Сервис {code}", "project_type": project_type})
    assert r.status_code == 200, r.text
    return r.json()


def test_ai_review_empty_draft_advisory(client, auth):
    A = auth["admin"]
    sid = _make_service(client, auth, "AIRE1")["id"]
    r = client.post(f"/api/services/{sid}/ai-review", headers=A, json={})
    assert r.status_code == 200, r.text
    d = r.json()
    # слой 2 без LLM честно помечен и находок не добавляет
    assert d["provider"] == "none" and d["llm_count"] == 0
    assert "LLM" in d["note"]
    # слой 1: обязательные по матрице mvp + карточка — warning; desired — info
    warns = [f for f in d["findings"] if f["severity"] == "warning"]
    arts = {f["artifact_kind"] for f in warns if f["artifact_kind"]}
    assert {"vision_c4", "api", "data_model", "config_build"} <= arts
    assert not any(f["artifact_kind"] == "adr" and f["severity"] == "warning" for f in d["findings"])
    assert any("Карточка" in f["title"] for f in warns)
    # advisory: находки — рекомендации, не блокеры
    assert all(f["severity"] in ("warning", "info") for f in d["findings"])
    # каждая находка ведёт внутрь DeepArch и размечена слоем
    assert all((f["target"] or "").startswith("#/service/") for f in d["findings"])
    assert all(f["layer"] == "formal" for f in d["findings"])
    assert d["formal_count"] == len(d["findings"])
    # прогон сохранён в историю
    last = client.get(f"/api/services/{sid}/ai-review", headers=A).json()
    assert last["id"] == d["id"] and last["formal_count"] == d["formal_count"]


def test_ai_review_history_dynamics(client, auth):
    A = auth["admin"]
    sid = _make_service(client, auth, "AIRE2")["id"]
    first = client.post(f"/api/services/{sid}/ai-review", headers=A, json={}).json()
    assert first["previous"] is None
    second = client.post(f"/api/services/{sid}/ai-review", headers=A, json={}).json()
    assert second["previous"]["id"] == first["id"]
    assert second["previous"]["total"] == first["formal_count"] + first["llm_count"]
    # серые находки («нет ссылки на исходник») исчезают после заполнения source_url
    r = client.put(f"/api/services/{sid}/artifacts/api", headers=A,
                   json={"content_md": "# API\nэндпоинты сервиса", "source_url": "https://git/api.md"})
    assert r.status_code == 200, r.text
    third = client.post(f"/api/services/{sid}/ai-review", headers=A, json={}).json()
    assert not any(f["artifact_kind"] == "api" and "нет ссылки на исходник" in f["title"]
                   for f in third["findings"])


def test_ai_review_nfr_targets_in_digits(client, auth):
    A = auth["admin"]
    sid = _make_service(client, auth, "AIRE3")["id"]
    r = client.put(f"/api/services/{sid}/artifacts/nfr_security", headers=A,
                   json={"content_md": "# NFR\nБыстро и надёжно, конкретных целей нет."})
    assert r.status_code == 200, r.text
    d = client.post(f"/api/services/{sid}/ai-review", headers=A, json={}).json()
    nfr_f = [f for f in d["findings"] if f["artifact_kind"] == "nfr_security"
             and f["severity"] == "warning"]
    assert any("в цифрах" in f["title"] for f in nfr_f)
    # с цифрами находка исчезает
    r = client.put(f"/api/services/{sid}/artifacts/nfr_security", headers=A,
                   json={"content_md": "# NFR\nRPS 500 запросов в секунду, p95 < 200ms, SLA 99.9%."})
    assert r.status_code == 200, r.text
    d = client.post(f"/api/services/{sid}/ai-review", headers=A, json={}).json()
    assert not any("в цифрах" in f["title"] for f in d["findings"])


def test_ai_review_requirements_coverage(client, auth):
    A = auth["admin"]
    sid = _make_service(client, auth, "AIRE4")["id"]
    r = client.post(f"/api/services/{sid}/requirements", headers=A,
                    json={"req_type": "nonfunc", "text": "Время ответа p95 < 200 мс", "ext_id": "НФТ-1"})
    assert r.status_code == 200, r.text
    d = client.post(f"/api/services/{sid}/ai-review", headers=A, json={}).json()
    cov = [f for f in d["findings"] if (f["target"] or "").endswith("/reqs")]
    assert cov and "НФТ-1" in cov[0]["detail"] and cov[0]["severity"] == "warning"
    # покрытие требованием в артефакте снимает находку (coverage ищет ext_id в тексте)
    r = client.put(f"/api/services/{sid}/artifacts/api", headers=A,
                   json={"content_md": "# API\nЭндпоинт платежей — покрытие требования НФТ-1: время ответа."})
    assert r.status_code == 200, r.text
    d = client.post(f"/api/services/{sid}/ai-review", headers=A, json={}).json()
    assert not any((f["target"] or "").endswith("/reqs") for f in d["findings"])


def test_ai_review_permissions(client, auth):
    sid = _make_service(client, auth, "AIRE5")["id"]
    # lead не имеет скоупа на чужой сервис, viewer — read-only
    for role in ("lead", "viewer"):
        r = client.post(f"/api/services/{sid}/ai-review", headers=auth[role], json={})
        assert r.status_code == 403, (role, r.text)
    # GET последнего прогона доступен на чтение любому аутентифицированному (прогон ещё не было)
    r = client.get(f"/api/services/{sid}/ai-review", headers=auth["viewer"])
    assert r.status_code == 200 and r.json() is None


def test_ai_precheck_deprecated(client, auth):
    r = client.post("/api/ai/precheck", headers=auth["admin"], json={"service_id": 1})
    assert r.status_code == 410, r.text
    assert "ai-review" in r.json()["detail"]


def test_parse_findings_json_salvage():
    """Ответ LLM, обрезанный лимитом токенов: собираем завершённые находки."""
    from app.ai_review import _parse_findings_json as parse
    ok = '{"findings":[{"kind":"риск","severity":"warning","title":"A","detail":"D"}]}'
    assert parse(ok)["findings"][0]["title"] == "A"
    # обрыв посреди строки: последняя завершённая находка спасается
    trunc = ('{"findings":[{"kind":"риск","severity":"warning","title":"A","detail":"D"},'
             '{"kind":"пробел","sever')
    r = parse(trunc)
    assert r and [f["title"] for f in r["findings"]] == ["A"]
    # мусор без JSON
    assert parse("никакого json здесь нет") is None


def test_standard_context_and_std_ref():
    """Промпт ревьюера обогащается разделами корпоративного стандарта (KB, Confluence DA);
    ссылка на пункт стандарта (std) нормализуется."""
    from app.ai_review import _normalize_llm_findings, _standard_context
    # KB-дайджест методологии ревью доступен без сети (статичный kb_data)
    ctx = _standard_context(1)
    assert ctx and "стандарт" in ctx.lower()
    assert "913353852" in repr(ctx) or "методолог" in ctx.lower() or "FR-" in ctx
    # std из ответа LLM: нормализация
    fs = _normalize_llm_findings({"findings": [
        {"kind": "несоответствие", "severity": "warning", "std": "  FR-14.2 ",
         "title": "ADR-002 противоречит Deployment", "detail": "d"},
        {"kind": "риск", "title": "нет std", "detail": "d"},
        {"kind": "риск", "title": "пустой std", "std": "   ", "detail": "d"},
    ]})
    assert fs[0]["std"] == "FR-14.2"
    assert fs[1]["std"] is None and fs[2]["std"] is None
