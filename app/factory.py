"""Service Factory (MVP2 BR-45…47): скаффолдинг сервиса по типу проекта.

При создании сервиса генерирует стартовый архитектурный пакет: все 7 артефактов
с шаблонным содержимым (по общему стандарту, pageId=894079737), пустой self-check
и подключённые approved-компоненты. Возвращает отчёт с next_steps по матрице
проектного типа: что обязательно заполнить перед ревью.
"""
import json
from .db import exec, q, q1, now
from .standards import ARTIFACT_KINDS, PROJECT_TYPES, CHECKLIST_ITEMS


def _vision(code, name, domain, project_type):
    pt = PROJECT_TYPES.get(project_type, {})
    return f"""## Architecture Vision — {name} ({code})

### 1. Контекстная диаграмма (C4 Level 1)
<!-- Система как «чёрный ящик» + внешние акторы: пользователи, смежные системы.
     Исходник диаграммы обязан храниться здесь: context-diagram.dsl (стандарт, §«В сухом остатке»). -->

### 2. Container Diagram (C4 Level 2)
<!-- Компоненты, границы, связи. Исходник: container-diagram.dsl -->

### 3. Ключевые бизнес-сценарии
1. <!-- основной поток ценности -->

### 4. Драйверы архитектуры
- Бизнес-цели: <!-- что и почему строим -->
- NFR: RPS ..., SLA ..., p95 ...
- Безопасность: <!-- PCI DSS / модель угроз, если применимо -->

> Сгенерировано Service Factory. Тип проекта: {project_type} — {pt.get('title', '')}."""


def _adr(code):
    return f"""## ADR — {code}

### ADR-001: Выбор языка программирования и основного фреймворка
- Контекст: <!-- требования и ограничения -->
- Варианты: ...
- Решение: ...
- Последствия: ...

### ADR-002: Выбор типа архитектуры (Монолит vs Микросервисы vs Модульный монолит)
- Контекст / Варианты / Решение / Последствия: ...

### ADR-003: Выбор СУБД и стратегии хранения данных
- Контекст / Варианты / Решение / Последствия: ...

### ADR-004: Стратегия аутентификации и авторизации
- Контекст / Варианты / Решение / Последствия: ... (референс: компонент Keycloak SSO)

### ADR-005: Стратегия логирования и мониторинга
- Контекст / Варианты / Решение / Последствия: ... (референс: компонент ECS Logging Starter)

> ADR фиксируют «почему»: контекст, альтернативы и последствия — не только вывод
> (само-чек, пункт 4; стандарт DA)."""


def _deployment(code):
    return f"""## Deployment — {code}

### Узлы и окружения
| Узел | Окружение (Dev/Test/Prod) | Назначение |
| --- | --- | --- |
| app | Dev | приложение |

### Каналы связи и протоколы
<!-- HTTP / gRPC / AMQP: кто с кем общается -->

### Конфигурация запуска
<!-- docker-compose.yml поднимает окружение одной командой: docker compose up -d -->"""


def _data_model(code):
    return f"""## Data Model — {code}

### ER-диаграмма
<!-- Концептуальная / логическая: сущности и связи. Исходник: schema.prisma / dbml, если требует стандарт. -->

### Соглашения об именовании
- Snake_case, без префиксов таблиц (или зафиксируйте иное).

### Политика хранения и безопасности данных
- Срок хранения: <!-- например, 5 лет для фин. проектов -->
- Маскирование: <!-- например, телефон: видны первые 3 и последние 2 цифры -->
- Версионирование схемы: <!-- если требуется аудит -->"""


def _api(code):
    return f"""## API Spec — {code}

### Контракт (OpenAPI / AsyncAPI)
- REST: файл `api/openapi.yaml` (Swagger) или событийные очереди: `asyncapi.yaml`.
- На старте достаточно 2–3 эндпоинта главного MVP-сценария, но строго:
  Backend и Frontend ведут параллельную работу на моках.

### Основные эндпоинты
| Метод | Путь | Назначение |
| --- | --- | --- |
| POST | /v1/... | <!-- главный сценарий --> |
| GET | /v1/... | <!-- главный сценарий --> |

### Версионирование
<!-- Политика breaking changes -->"""


def _nfr(code):
    return f"""## NFR & Security profile — {code}

### Производительность
- RPS (пиковый): ...
- Время ответа: p95 < ... ms
- Одновременные пользователи: ...

### Масштабирование и отказоустойчивость
- Горизонтальное / вертикальное; критерии скейлинга: ...
- RTO: ... ч, RPO: ... мин

### Безопасность
- Модель угроз («кто может украсть / сломать»): ...
- Шифрование: в БД и на транспортном уровне — ...
- Соответствие требованиям: <!-- PCI DSS, если платёжный контур -->

> NFR должны быть цифрами — иначе не проверяются в fitness/NFR-валидации (BR-51…53)."""


def _config_build(code):
    return f"""## Config & Build Mgmt — {code}

### Переменные окружения
- Репер: `.env.example` в репозитории — что нужно для запуска.

### Локальный запуск
- `docker compose up -d` поднимает всё окружение одной командой.

### Сборка и CI
- <!-- Пайплайн (GitLab CI), версии инструментов, публикация артефактов -->"""


def _threat_model(code):
    return f"""## Threat Model — {code}

### Границы доверия и активы
- <!-- диаграмма контекста с границами доверия; активы: ПДн/платёжные данные, доступы, доступность -->

### Сценарии угроз (STRIDE)
| # | Категория | Сценарий | Контрмера | Статус |
|---|-----------|----------|-----------|--------|
| T1 | Spoofing | <!-- ... --> | <!-- ... --> | open |
| T2 | Tampering | <!-- ... --> | <!-- ... --> | planned |

### Связь с другими артефактами
- Контрмеры auth — в ADR-004; требования доступности и шифрования — в NFR & Security profile.
- Матрица обязательности: критические и высоконагруженные B2C-системы (см. матрицу типов проектов)."""


def _drp_bcp(code):
    return f"""## DRP & BCP — {code}

### Критичность и цели восстановления
- Критичность для бизнеса: <!-- ... -->
- RTO: ... ч · RPO: ... мин <!-- должны сходиться с NFR & Security profile -->

### Сценарии отказа
| Сценарий | Влияние | Реакция | Ответственный |
|----------|---------|---------|---------------|
| <!-- отказ Зоны доступности --> | <!-- ... --> | <!-- ... --> | <!-- ... --> |

### Резервирование и восстановление
- Бэкапы: расписание, глубина хранения, <b>проверка восстановления</b> (не реже раза в квартал).
- Резервный контур: <!-- регион/зона доступности, auto-failover или ручной план -->"""


_TEMPLATES = {"vision_c4": _vision, "adr": _adr, "deployment": _deployment,
              "data_model": _data_model, "api": _api, "nfr_security": _nfr,
              "config_build": _config_build,
              "threat_model": _threat_model, "drp_bcp": _drp_bcp}


def scaffold_missing(service_id: int, updated_by: str) -> list[str]:
    """Создаёт скелеты (шаблоны стандарта) для обязательных артефактов типа,
    которых ещё нет или которые пусты. Возвращает список созданных kind."""
    svc = q1("SELECT * FROM services WHERE id=?", (service_id,))
    if not svc:
        return []
    pt = PROJECT_TYPES.get(svc["project_type"], {})
    mandatory = [k for k, v in pt.get("matrix", {}).items() if v == "mandatory"]
    existing = {a["kind"]: a for a in
                q("SELECT kind, content_md FROM artifacts WHERE service_id=?", (service_id,))}
    created = []
    for kind in mandatory:
        cur = existing.get(kind)
        if cur and (cur["content_md"] or "").strip():
            continue
        content = _TEMPLATES[kind](svc["code"], svc["name"], svc["domain"],
                                   svc["project_type"]) if kind == "vision_c4" \
            else _TEMPLATES[kind](svc["code"])
        if cur:   # строка есть, но контента нет — обновляем
            exec("UPDATE artifacts SET content_md=?, version=version+1, updated_by=?, "
                 "updated_at=? WHERE service_id=? AND kind=?",
                 (content, updated_by, now(), service_id, kind))
        else:
            exec("INSERT INTO artifacts(service_id,kind,content_md,version,updated_by,updated_at)"
                 " VALUES(?,?,?,?,?,?)", (service_id, kind, content, 1, updated_by, now()))
        created.append(kind)
    return created


def scaffold(code, name, domain, project_type, owner, architect,
             created_by, lifecycle="design"):
    """Создаёт сервис + стартовый архитектурный пакет + отчёт next_steps."""
    if q1("SELECT id FROM services WHERE code=?", (code,)):
        raise ValueError(f"Сервис с кодом {code} уже есть")
    sid = exec("INSERT INTO services(code,name,domain,owner,architect,project_type,"
               "lifecycle,review_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (code, name, domain, owner, architect, project_type, lifecycle,
                "draft", now(), now()))
    for a in ARTIFACT_KINDS:
        kind = a["kind"]
        content = _TEMPLATES[kind](code, name, domain, project_type) if kind == "vision_c4" \
            else _TEMPLATES[kind](code)
        exec("INSERT INTO artifacts(service_id,kind,content_md,version,updated_by,updated_at)"
             " VALUES(?,?,?,?,?,?)", (sid, kind, content, 1, created_by, now()))
    exec("INSERT INTO checklist_runs(service_id,answers,score_pct,mandatory_missing,"
         "created_by,created_at) VALUES(?,?,?,?,?,?)",
         (sid, json.dumps([]), 0.0, 0, created_by, now()))
    # подключаем все approved-компоненты каталога (compliance by construction, BR-14)
    attached = []
    for c in q("SELECT id, name FROM components WHERE status='approved'"):
        exec("INSERT OR IGNORE INTO service_components(service_id,component_id) VALUES(?,?)",
             (sid, c["id"]))
        attached.append(c["name"])
    pt = PROJECT_TYPES.get(project_type, {})
    mandatory = [k for k, v in pt.get("matrix", {}).items() if v == "mandatory"]
    next_steps = [
        f"Заполните обязательные артефакты для типа «{pt.get('title', project_type)}»: "
        + ", ".join(mandatory),
        "Зафиксируйте NFR цифрами (RPS, p95, SLA) — после этого доступна NFR-валидация",
        "Загрузите исходники диаграмм (context/container .dsl) — их проверяет fitness-правило",
        "Пройдите self-check (10 пунктов Е/Ч/Н) перед отправкой на ревью",
        "Отправьте сервис на ревью эксперту домена",
    ]
    return {"id": sid, "code": code, "artifacts": len(ARTIFACT_KINDS),
            "components_attached": attached, "next_steps": next_steps}
