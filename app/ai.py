"""
AI-адаптер (BR-27, BR-28).

MVP: provider="mock" — детерминированные эвристики без внешней LLM.
В проде сюда подключается клиент корпоративной платформы AI-Buddy
(см. Confluence: "SDLC Агент соответствия архитектурным стандартам" pageId=915912563).
Все результаты advisory-only, с evidence-ссылками (BR-32), решение за человеком (BR-33).
AI Gate (BR-29) упразднён 2026-11-07: формальный слой модуля ai_review его поглощает.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor

from . import llm, reqs
from .db import q, q1
from .kb import retrieve
from .standards import ARTIFACT_KINDS, PROJECT_TYPES

# Виды, у которых AI-черновик генерирует и Mermaid-исходник диаграммы (решение 2026-11-07:
# deployment и data_model — «пересказ реальности», где AI-черновик лучше пустого холста;
# vision_c4 исключён — его диаграмма является производной C4-редактора «Проектирования»).
AI_DIAG_KINDS = ("deployment", "data_model")
_DIAG_HEADER = {"deployment": "C4Deployment", "data_model": "erDiagram"}

DIAG_SYSTEM = """Ты архитектурный ассистент компании ДАТС. Составь Mermaid-исходник диаграммы
и верни СТРОГО код Mermaid без markdown-ограждений (``` не пиши) и без пояснений.
Правила:
1. Для deployment верни диаграмму вида C4Deployment: вложенные Deployment_Node(окружения,
   кластеры) → Container/ContainerDb из компонентов сервиса; для data_model — диаграмму
   вида erDiagram: сущности из требований и API-спецификации, связи с кратностью
   (||--o{, ||--|{, }o--|| и т.п.) и русские подписи.
2. Опирайся только на факты о сервисе; неизвестное помечай [TODO] в подписях, не выдумывай узлы.
3. Код должен быть валидным: баланс фигурных скобок, экранированные спецсимволы в подписях.
4. Это черновик (advisory, BR-33): автор обязан проверить и подтвердить его."""

DRAFT_SYSTEM = """Ты архитектурный ассистент компании ДАТС. Составь черновик архитектурного артефакта.
Правила:
1. Опирайся на требования стандарта (контекст ниже) и фактические данные сервиса. Структуру сохрани по шаблону.
2. Всё, что выводится из данных сервиса, заполняй сразу; вместо неизвестного поставь [TODO: что уточнить].
3. Формат: markdown, по-русски, без вступлений и прощаний — только содержимое артефакта.
4. Это черновик: автор обязан проверить и подтвердить его (advisory, BR-33)."""


def _artifact(service_id, kind):
    return q1("SELECT * FROM artifacts WHERE service_id=? AND kind=?", (service_id, kind))


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


def _mq(s: str) -> str:
    """Экранирует свободный текст (имена сервисов/компонентов) для Mermaid-строк."""
    return (s or "").replace('"', "'").replace("{", "(").replace("}", ")")


def _mock_diagram(svc, kind: str) -> str:
    """Skeleton-диаграмма без LLM: осмысленный стартовый Mermaid с [TODO] в подписях."""
    comps = q("SELECT c.name, c.kind FROM components c "
              "JOIN service_components sc ON sc.component_id=c.id "
              "WHERE sc.service_id=? LIMIT 8", (svc["id"],))
    if kind == "deployment":
        # контейнеры внутри ноды приложения — из фактических компонентов каталога;
        # БД у компонентов отдельного kind нет, поэтому ищем по имени/тех. упоминаниям
        inner, db_line = [], ""
        for c in comps:
            key = f"{c['kind'] or ''} {c['name'] or ''}".lower()
            name = _mq(c["name"]) or "[TODO]"
            if not db_line and re.search(r"\bdb\b|database|бд|postgres|mysql|clickhouse|mongo", key):
                db_line = f'    ContainerDb(db1, "{name}", "[TODO] тех.", "")'
            else:
                inner.append(f'        Container(c{len(inner) + 1}, "{name}", "[TODO] тех.", "")')
        if not inner:
            inner = ['        Container(c1, "[TODO] контейнер из компонентов каталога", "[TODO] тех.", "")']
        body = "\n".join(inner)
        return f"""C4Deployment
title Deployment — {_mq(svc['name'])} ({svc['code']})

Deployment_Node(prod, "Prod-окружение", "[TODO] кластер/хостинг"){{
    Deployment_Node(app, "Приложение", "[TODO] k8s namespace / ВМ"){{
{body}
    }}
{db_line or '    ContainerDb(db1, "[TODO] БД", "[TODO] тех.", "")'}
}}

Rel(app, db1, "[TODO] протокол доступа к данным")"""
    # data_model
    return """erDiagram
    %% Черновик: сущности выведите из требований и API-спецификации
    ENTITY_A ||--o{ ENTITY_B : "[TODO] связь"
    ENTITY_A {
        int id PK
        varchar name "[TODO] поля из API-спецификации"
    }"""


def _clean_mermaid(text: str) -> str:
    """Снимает markdown-ограждения, если LLM их всё же прислала."""
    t = (text or "").strip()
    m = re.search(r"```(?:mermaid)?\s*\n(.*?)```", t, re.DOTALL)
    if m:
        t = m.group(1).strip()
    return t


def _valid_diag(kind: str, code: str) -> bool:
    """Санити-проверка LLM-диаграммы: правильный заголовок и баланс скобок у C4."""
    if not code or len(code) > 12000:
        return False
    if not code.lstrip().startswith(_DIAG_HEADER[kind]):
        return False
    return not (kind == "deployment" and code.count("{") != code.count("}"))


def draft_diagram(service_id: int, kind: str, model: str = "", svc=None) -> str | None:
    """Mermaid-исходник диаграммы артефакта (deployment/data_model): LLM по фактам сервиса,
    при недоступности/некорректном ответе — skeleton-фоллбек. None — для видов без диаграмм."""
    if kind not in AI_DIAG_KINDS:
        return None
    svc = svc or q1("SELECT * FROM services WHERE id=?", (service_id,))
    if not svc:
        return None
    skeleton = _mock_diagram(svc, kind)
    if not llm.configured():
        return skeleton
    user_prompt = (f"Вид диаграммы: {_DIAG_HEADER[kind]} для артефакта «{kind}».\n\n"
                   f"Факты о сервисе:\n{_service_facts(service_id)}\n\n"
                   f"Составь Mermaid-исходник ({_DIAG_HEADER[kind]}) для сервиса {svc['code']}.")
    try:
        raw = llm.chat([{"role": "system", "content": DIAG_SYSTEM},
                        {"role": "user", "content": user_prompt}],
                       temperature=0.2, max_tokens=2500, model=model)
        code = _clean_mermaid(raw)
        return code if _valid_diag(kind, code) else skeleton
    except llm.LLMError:
        return skeleton


def draft_artifact(service_id: int, kind: str, model: str = "", focus: str = "") -> dict:
    """AI-черновик артефакта (BR-28): живой AI-Buddy по контексту сервиса и KB стандарта,
    при недоступности LLM — детерминированный шаблон (fallback).
    focus — акцент из находки AI-ревью (кнопка «Исправить»): LLM прорабатывает её.
    Текст и диаграмма генерируются параллельно (два вызова LLM ~30 с вместо ~60 с последовательно)."""
    svc = q1("SELECT * FROM services WHERE id=?", (service_id,))
    art = next((a for a in ARTIFACT_KINDS if a["kind"] == kind), None)
    if not svc or not art:
        return None
    body = _mock_draft(svc, kind, art)
    if not llm.configured():
        diag = draft_diagram(service_id, kind, model=model, svc=svc)
        return {"service_id": service_id, "kind": kind, "provider": "mock", "model": None,
                "content_md": body, **({"diagram_code": diag} if diag else {}),
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
                   + (f"Особый акцент (замечание AI-ревью — обязательно проработать):\n"
                      f"{focus.strip()}\n\n" if (focus or "").strip() else "")
                   + f"Составь черновик артефакта «{art['title']}» для сервиса {svc['code']}.")
    try:
        diag = None
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_diag = ex.submit(draft_diagram, service_id, kind, model)   # internal LLMError → skeleton
            f_text = ex.submit(llm.chat,
                               [{"role": "system", "content": DRAFT_SYSTEM},
                                {"role": "user", "content": user_prompt}],
                               temperature=0.3, max_tokens=4000, model=model)
            text = f_text.result()
            diag = f_diag.result()
        if not text.strip():
            raise llm.LLMError("LLM вернула пустой ответ")
        return {"service_id": service_id, "kind": kind, "provider": "ai-buddy",
                "model": (model or "").strip() or llm.config()[2],
                "content_md": text.strip(), **({"diagram_code": diag} if diag else {}),
                "note": "AI-черновик (AI-Buddy) — требует подтверждения автора (BR-28/BR-33)"}
    except llm.LLMError as e:
        return {"service_id": service_id, "kind": kind, "provider": "mock", "model": None,
                "content_md": body, **({"diagram_code": diag} if diag else {}),
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
