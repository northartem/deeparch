"""
AI-адаптер (BR-27, BR-28, BR-29).

MVP: provider="mock" — детерминированные эвристики без внешней LLM.
В проде сюда подключается клиент корпоративной платформы AI-Buddy
(см. Confluence: "SDLC Агент соответствия архитектурным стандартам" pageId=915912563).
Все результаты advisory-only, с evidence-ссылками (BR-32), решение за человеком (BR-33).
"""
import json
from .db import q, q1
from .standards import CHECKLIST_ITEMS, GRADES, ARTIFACT_KINDS, STANDARD_REF

MIN_CONTENT = 200  # эвристика: артефакт содержательнее 200 символов


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


def draft_artifact(service_id: int, kind: str):
    """AI-черновик артефакта по шаблону стандарта (BR-28)."""
    svc = q1("SELECT * FROM services WHERE id=?", (service_id,))
    art = next((a for a in ARTIFACT_KINDS if a["kind"] == kind), None)
    if not svc or not art:
        return None
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
    return {"service_id": service_id, "kind": kind, "provider": "mock",
            "content_md": body, "note": "AI-generated draft — требует подтверждения автора (BR-28/BR-33)"}
