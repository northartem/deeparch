"""
AI-адаптер (BR-27, BR-28, BR-29).

MVP: provider="mock" — детерминированные эвристики без внешней LLM.
В проде сюда подключается клиент корпоративной платформы AI-Buddy
(см. Confluence: "SDLC Агент соответствия архитектурным стандартам" pageId=915912563).
Все результаты advisory-only, с evidence-ссылками (BR-32), решение за человеком (BR-33).
"""
import json
import re

from . import llm, reqs
from .db import q, q1
from .kb import retrieve
from .standards import ARTIFACT_KINDS, CHECKLIST_ITEMS, PROJECT_TYPES

MIN_CONTENT = 200  # эвристика: артефакт содержательнее 200 символов

DRAFT_SYSTEM = """Ты архитектурный ассистент компании ДАТС. Составь черновик архитектурного артефакта.
Правила:
1. Опирайся на требования стандарта (контекст ниже) и фактические данные сервиса. Структуру сохрани по шаблону.
2. Всё, что выводится из данных сервиса, заполняй сразу; вместо неизвестного поставь [TODO: что уточнить].
3. Формат: markdown, по-русски, без вступлений и прощаний — только содержимое артефакта.
4. Это черновик: автор обязан проверить и подтвердить его (advisory, BR-33)."""


def _artifact(service_id, kind):
    return q1("SELECT * FROM artifacts WHERE service_id=? AND kind=?", (service_id, kind))


def predict_checklist(service_id: int):
    """AI Gate (BR-29): предсказывает Е/Ч/Н по чек-листу на основе фактического наполнения артефактов."""
    svc = q1("SELECT * FROM services WHERE id=?", (service_id,))
    if not svc:
        return None
    predictions, issues = [], []
    for it in CHECKLIST_ITEMS:
        grade, evidence = "N", None
        if it["artifact"] is None:  # пункт 10 — карточка сервиса
            filled = all([svc["owner"], svc["domain"], svc["name"]])
            grade, evidence = ("E", f"Карточка: владелец={svc['owner']}, домен={svc['domain']}") if filled else ("N", "Карточка заполнена не полностью")
        else:
            a = _artifact(service_id, it["artifact"])
            if a and a["content_md"] and len(a["content_md"]) >= MIN_CONTENT:
                grade = "E"
                if a["source_url"]:
                    evidence = f"Артефакт «{it['artifact']}», исх.: {a['source_url']}"
                else:
                    grade = "Ch"
                    evidence = f"Артефакт «{it['artifact']}» заполнен, но нет ссылки на исходник"
            else:
                evidence = f"Артефакт «{it['artifact']}» пуст или слишком краток"
        if it["weight"] == "mandatory" and grade != "E":
            issues.append({"severity": "blocking" if grade == "N" else "warning",
                           "item": it["item"], "hint": evidence})
        predictions.append({"item_id": it["id"], "item": it["item"], "predicted": grade, "evidence": evidence})
    return {"service_id": service_id, "provider": "mock", "mode": "advisory",
            "predictions": predictions, "issues": issues}


def _service_facts(service_id: int, max_art: int = 400) -> str:
    """Факты о сервисе для промпта: карточка, компоненты, состояние артефактов."""
    svc = q1("SELECT * FROM services WHERE id=?", (service_id,))
    comps = q("SELECT c.name, c.kind, c.status FROM components c "
              "JOIN service_components sc ON sc.component_id=c.id "
              "WHERE sc.service_id=? LIMIT 20", (service_id,))
    arts = q("SELECT kind, content_md, diagram_code, source_url FROM artifacts "
             "WHERE service_id=? ORDER BY kind", (service_id,))
    lines = [(f"Сервис: {svc['name']} ({svc['code']}), домен: {svc['domain'] or '—'}, "
              f"тип проекта: {svc['project_type']}, жизненный цикл: {svc['lifecycle']}, "
              f"владелец: {svc['owner'] or '—'}, архитектор: {svc['architect'] or '—'}.")]
    # входящие требования — исходник, из которого проектируется архитектура
    reqs = q("SELECT req_type, ext_id, text FROM requirements WHERE service_id=? "
             "ORDER BY req_type, id LIMIT 20", (service_id,))
    if reqs:
        lines.append("Требования, на основе которых проектируется архитектура:")
        lines += [f"- {r['ext_id']} ({'НФТ' if r['req_type'] == 'nonfunc' else 'ФТ'}): {r['text']}"
                  for r in reqs]
    if comps:
        lines.append("Компоненты: " + "; ".join(
            f"{c['name']} ({c['kind']}, {c['status']})" for c in comps) + ".")
    if arts:
        lines.append("Артефакты сервиса:")
        for a in arts:
            filled = "заполнен" if (a["content_md"] or "").strip() else "пуст"
            extra = ", есть диаграмма" if (a["diagram_code"] or "").strip() else ""
            snippet = (a["content_md"] or "").strip()[:max_art]
            lines.append(f"- {a['kind']} — {filled}{extra}."
                         + (f" Начало содержания: {snippet}" if snippet else ""))
    return "\n".join(lines)


def draft_artifact(service_id: int, kind: str, model: str = "") -> dict:
    """AI-черновик артефакта (BR-28): живой AI-Buddy по контексту сервиса и KB стандарта,
    при недоступности LLM — детерминированный шаблон (fallback)."""
    svc = q1("SELECT * FROM services WHERE id=?", (service_id,))
    art = next((a for a in ARTIFACT_KINDS if a["kind"] == kind), None)
    if not svc or not art:
        return None
    body = _mock_draft(svc, kind, art)
    if not llm.configured():
        return {"service_id": service_id, "kind": kind, "provider": "mock", "model": None,
                "content_md": body,
                "note": "Черновик по шаблону стандарта (LLM не подключена) — требует подтверждения автора (BR-28/BR-33)"}

    # требования стандарта: релевантные чанки KB + спецификация артефакта
    query = f"{art['title']}. {art['question']} {art['captures']}"
    std_ctx = "\n\n".join(f"[{i}] {c['title']}: {c['chunk']}"
                          for i, c in enumerate(retrieve(query, 3), 1))
    user_prompt = (f"Спецификация артефакта «{art['title']}» (kind={kind}):\n"
                   f"- Вопрос, на который отвечает артефакт: {art['question']}\n"
                   f"- Что фиксирует: {art['captures']}\n"
                   f"- Обязательные разделы/исходники: {', '.join(art['required_artifacts'])}\n"
                   f"- Шаблон стандарта: {art['template_ref']}\n\n"
                   f"Требования стандарта (KB):\n{std_ctx}\n\n"
                   f"Факты о сервисе:\n{_service_facts(service_id)}\n\n"
                   f"Составь черновик артефакта «{art['title']}» для сервиса {svc['code']}.")
    try:
        text = llm.chat([{"role": "system", "content": DRAFT_SYSTEM},
                         {"role": "user", "content": user_prompt}],
                        temperature=0.3, max_tokens=4000, model=model)
        if not text.strip():
            raise llm.LLMError("LLM вернула пустой ответ")
        return {"service_id": service_id, "kind": kind, "provider": "ai-buddy",
                "model": (model or "").strip() or llm.config()[2],
                "content_md": text.strip(),
                "note": "AI-черновик (AI-Buddy) — требует подтверждения автора (BR-28/BR-33)"}
    except llm.LLMError as e:
        return {"service_id": service_id, "kind": kind, "provider": "mock", "model": None,
                "content_md": body,
                "note": f"LLM недоступна ({e}) — черновик по шаблону стандарта; требует подтверждения автора (BR-28/BR-33)"}


def _mock_draft(svc, kind: str, art) -> str:
    if kind == "vision_c4":
        body = f"""## Architecture Vision — {svc['name']} ({svc['code']})

Тип проекта: {svc['project_type']}. Домен: {svc['domain'] or '—'}.

### 1. Контекстная диаграмма (C4 L1)
[TODO: система как чёрный ящик + внешние акторы; исходник: context-diagram.dsl]

### 2. Container Diagram (C4 L2)
[TODO: компоненты, границы, связи; исходник: container-diagram.dsl]

### 3. Ключевые бизнес-сценарии
1. [TODO]

### 4. Драйверы архитектуры
- Бизнес-цели: [TODO]
- NFR: RPS=[TODO], SLA=[TODO], безопасность=[TODO]
"""
    elif kind == "adr":
        body = f"""## ADR-00X: [название решения] — {svc['name']}

**Статус:** proposed · **Дата:** [дата] · **Автор:** [автор]

### Контекст
[TODO]

### Альтернативы
1. [вариант A] — плюсы/минусы
2. [вариант B] — плюсы/минусы

### Решение и обоснование
[TODO]

### Последствия
- [TODO]
"""
    elif kind == "nfr_security":
        body = f"""## NFR & Security profile — {svc['name']}

| Метрика | Значение |
| --- | --- |
| RPS | [TODO] |
| Время ответа p95 | [TODO] < 200ms |
| SLA / доступность | [TODO] |
| Масштабирование | [горизонтальное/вертикальное], критерии скейлинга |

### Модель угроз («Кто может украсть / сломать»)
[TODO]

### Шифрование
- Транспорт: [TODO] · БД: [TODO]
"""
    else:
        body = f"""## {art['title']} — {svc['name']}

Вопрос: {art['question']}

Что фиксируем: {art['captures']}

[TODO — заполните по шаблону] ({art['template_ref']})
"""
    return body


# --- Design Session (сценарий A): документ → черновик карточки сервиса + требования --

EXTRACT_SYSTEM = """Ты помогаешь завести сервис в системе архитектурного проектирования ДАТС.
Из вставленного документа (ТЗ, письмо, описание задачи) извлеки данные сервиса
и верни СТРОГО JSON-объект:
{"code": "латинский код сервиса, 3-10 символов, верхний регистр, или null",
 "name": "название сервиса по-русски или null",
 "domain": "домен/направление или null",
 "project_type": "один из: TYPE_KEYS, или null",
 "summary": "суть сервиса в 1-2 предложениях или null",
 "requirements": [{"type": "ФТ" | "НФТ", "text": "формулировка требования"}]}
Правила:
1. Чего нет в документе — ставь null, не придумывай.
2. Требования — только те, что прямо следуют из документа; формулировки сохраняй близко к оригиналу.
3. Только JSON без пояснений."""


def extract_service(text: str, model: str = "") -> dict:
    """Черновик карточки сервиса + требования из свободного документа (advisory, BR-33):
    результат только предзаполняет форму — решение за человеком."""
    text = (text or "").strip()
    if not text:
        return {"provider": "none", "draft": _fallback_extract("")}
    if llm.configured():
        prompt = EXTRACT_SYSTEM.replace("TYPE_KEYS", ", ".join(PROJECT_TYPES))
        try:
            raw = llm.chat([{"role": "system", "content": prompt},
                            {"role": "user", "content": text[:12000]}],
                           temperature=0.1, max_tokens=4000, model=model)
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                draft = _normalize_extract(json.loads(m.group(0)))
                if draft is not None:
                    return {"provider": "ai-buddy", "draft": draft}
        except (llm.LLMError, ValueError, KeyError, TypeError):
            pass
    return {"provider": "fallback", "draft": _fallback_extract(text)}


def _normalize_extract(raw: dict) -> dict | None:
    """Приводит ответ LLM к безопасной форме; None — если ответ вообще не о сервисе."""
    if not isinstance(raw, dict):
        return None
    name = (raw.get("name") or "").strip() or None
    code = (raw.get("code") or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9_-]{2,16}", code):
        code = None
    pt = raw.get("project_type")
    pt = pt if pt in PROJECT_TYPES else None
    reqs_out = []
    for it in (raw.get("requirements") or []):
        t = (it.get("text") or "").strip()
        if not t:
            continue
        typ = "nonfunc" if str(it.get("type", "")).upper().startswith("Н") else "func"
        reqs_out.append({"req_type": typ, "text": t})
    if not (name or code or reqs_out):
        return None
    return {"code": code, "name": name, "domain": (raw.get("domain") or "").strip() or None,
            "project_type": pt, "summary": (raw.get("summary") or "").strip() or None,
            "requirements": reqs_out}


def _fallback_extract(text: str) -> dict:
    """Без LLM: первая значимая строка — название, латиница в тексте — кандидат в код,
    требования — построчная эвристика parse_document."""
    lines = [ln.strip().lstrip("#-*•·0123456789. ").strip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if len(ln) > 3]
    m = re.search(r"\b[A-Za-z]{3,10}\b", text or "")
    return {"code": m.group(0).upper()[:10] if m else None,
            "name": lines[0][:80] if lines else None,
            "domain": None, "project_type": "mvp", "summary": None,
            "requirements": [{"req_type": it["req_type"], "text": it["text"]}
                             for it in reqs._naive_parse(text or "")]}
