"""
Данные корпоративного стандарта "Architecture Definition Set".

Источник: Confluence dats.tech
  - Общий архитектурный стандарт (Architecture Definition Set) — pageId=894079737
  - Навигатор по артефактам архитектурного стандарта — pageId=924778815
  - Self-check чек-лист — pageId=918379090
"""

STANDARD_NAME = "Общий архитектурный стандарт (Architecture Definition Set)"
STANDARD_REF = "https://confluence.dats.tech/pages/viewpage.action?pageId=894079737"

# --- 9 артефактов стандарта ----------------------------------------------------
# (7 базовых + threat_model и drp_bcp: обязательны для critical/b2c_highload по
#  «Минимальному набору документов по типам проектов» — pageId=896409016)

ARTIFACT_KINDS = [
    {
        "kind": "vision_c4",
        "title": "Architecture Vision + C4",
        "question": "Что строим и где проходят границы системы?",
        "captures": "Контекст, акторы, внешние системы, контейнеры (C4 L1/L2), ключевые сценарии и драйверы.",
        "required_artifacts": ["context-diagram (png/dsl/json), container-diagram (png/dsl/json) — с исходниками"],
        "template_ref": "https://confluence.dats.tech/pages/viewpage.action?pageId=903905911",
    },
    {
        "kind": "adr",
        "title": "ADR — каталог решений",
        "question": "Почему выбрано именно это решение?",
        "captures": "Контекст, альтернативы, решение, обоснование, последствия.",
        "required_artifacts": ["ADR-001 стек", "ADR-002 тип архитектуры", "ADR-003 СУБД", "ADR-004 auth (желательно)", "ADR-005 логирование (желательно)"],
        "template_ref": "https://confluence.dats.tech/pages/viewpage.action?pageId=903905836",
    },
    {
        "kind": "deployment",
        "title": "Deployment Diagram",
        "question": "Где и как работает система?",
        "captures": "Узлы, окружения (Dev/Test/Prod), каналы связи, протоколы.",
        "required_artifacts": ["deployment-диаграмма с окружениями"],
        "template_ref": "https://confluence.dats.tech/pages/viewpage.action?pageId=903906114",
    },
    {
        "kind": "api",
        "title": "API-спецификация",
        "question": "Как системы и компоненты взаимодействуют?",
        "captures": "Контракты OpenAPI / AsyncAPI, версии, операции, модели обмена.",
        "required_artifacts": ["openapi.yaml / asyncapi.yaml — 2–3 эндпоинта MVP-сценария"],
        "template_ref": "https://confluence.dats.tech/pages/viewpage.action?pageId=903906146",
    },
    {
        "kind": "data_model",
        "title": "Модель данных",
        "question": "Как устроены, связаны и хранятся данные?",
        "captures": "Сущности, связи, владение, маскирование, версионирование, наименования.",
        "required_artifacts": ["er-diagram.png / schema.prisma / dbml — если требует стандарт"],
        "template_ref": "https://confluence.dats.tech/pages/viewpage.action?pageId=903906141",
    },
    {
        "kind": "nfr_security",
        "title": "NFR & Security profile",
        "question": "Каким требованиям должна соответствовать система?",
        "captures": "RPS, время ответа (p95), масштабирование, модель угроз, шифрование, наблюдаемость.",
        "required_artifacts": ["non-functional-requirements с цифрами"],
        "template_ref": "https://confluence.dats.tech/pages/viewpage.action?pageId=903906125",
    },
    {
        "kind": "config_build",
        "title": "Config & Build Management",
        "question": "Как воспроизводимо собрать, настроить и запустить систему?",
        "captures": "Конфигурации, зависимости, сборка, CI/CD, секреты.",
        "required_artifacts": ["docker-compose.yml", ".env.example"],
        "template_ref": "https://confluence.dats.tech/pages/viewpage.action?pageId=903909162",
    },
    {
        "kind": "threat_model",
        "title": "Threat Model",
        "question": "Какие угрозы актуальны и чем они закрыты?",
        "captures": "Границы доверия, активы, сценарии угроз (STRIDE), контрмеры и их статус.",
        "required_artifacts": ["threat-model: диаграмма границ доверия + таблица угроз с митигациями"],
        "template_ref": "https://confluence.dats.tech/pages/viewpage.action?pageId=896409016",
    },
    {
        "kind": "drp_bcp",
        "title": "DRP & BCP",
        "question": "Как система восстанавливается после отказа?",
        "captures": "RTO/RPO, сценарии отказа и реакции, бэкапы и проверка восстановления, резервный контур.",
        "required_artifacts": ["drp/bcp-документ: RTO/RPO, сценарии отказа, план восстановления"],
        "template_ref": "https://confluence.dats.tech/pages/viewpage.action?pageId=896409016",
    },
]

# --- Self-check чек-лист (10 пунктов, Е/Ч/Н) -----------------------------------

CHECKLIST_ITEMS = [
    {"id": 1,  "item": "C4 System Context (L1)", "expected": "context-diagram (png/dsl/json): система как чёрный ящик + внешние акторы; есть исходник", "weight": "mandatory", "artifact": "vision_c4"},
    {"id": 2,  "item": "C4 Container", "expected": "container-diagram (png/dsl/json): компоненты, границы, связи; есть исходник", "weight": "mandatory", "artifact": "vision_c4"},
    {"id": 3,  "item": "Deployment-диаграмма", "expected": "Узлы, каналы связи и протоколы, окружения (Dev/Test/Prod)", "weight": "mandatory", "artifact": "deployment"},
    {"id": 4,  "item": "ADR: стек и тип архитектуры", "expected": "ADR-001…003 с контекстом, альтернативами и последствиями", "weight": "mandatory", "artifact": "adr"},
    {"id": 5,  "item": "ADR: аутентификация и логирование", "expected": "ADR-004, ADR-005", "weight": "desired", "artifact": "adr"},
    {"id": 6,  "item": "API-спецификация", "expected": "openapi.yaml / asyncapi.yaml: 2–3 эндпоинта MVP-сценария", "weight": "mandatory", "artifact": "api"},
    {"id": 7,  "item": "Модель данных", "expected": "ER-диаграмма либо schema.prisma/dbml; соглашения об именовании", "weight": "optional", "artifact": "data_model"},
    {"id": 8,  "item": "NFR-профиль", "expected": "Цифры: RPS, p95, критерии масштабирования, модель угроз", "weight": "desired", "artifact": "nfr_security"},
    {"id": 9,  "item": "Config & Build", "expected": "docker-compose.yml поднимает окружение одной командой, есть .env.example", "weight": "optional", "artifact": "config_build"},
    {"id": 10, "item": "Карточка сервиса", "expected": "Владелец, назначение, контекст — в одном месте", "weight": "mandatory", "artifact": None},
]

GRADES = {"E": 1.0, "Ch": 0.5, "N": 0.0}  # Есть / Частично / Отсутствует

# --- Типы проектов: матрица глубины артефактов ---------------------------------
# req: mandatory / desired / optional — по «Минимальным наборам по типам проектов»

PROJECT_TYPES = {
    "landing": {
        "title": "Landing / Промо-сайт",
        "matrix": {"vision_c4": "mandatory", "adr": "optional", "deployment": "mandatory", "api": "optional", "data_model": "optional", "nfr_security": "desired", "config_build": "mandatory"},
    },
    "crm": {
        "title": "Внутренний CRM / Back-office",
        "matrix": {"vision_c4": "mandatory", "adr": "optional", "deployment": "optional", "api": "desired", "data_model": "mandatory", "nfr_security": "optional", "config_build": "mandatory"},
    },
    "mvp": {
        "title": "MVP",
        "matrix": {"vision_c4": "mandatory", "adr": "desired", "deployment": "desired", "api": "mandatory", "data_model": "mandatory", "nfr_security": "desired", "config_build": "mandatory"},
    },
    "b2c_highload": {
        "title": "Высоконагруженный B2C",
        "matrix": {"vision_c4": "mandatory", "adr": "mandatory", "deployment": "mandatory", "api": "mandatory", "data_model": "mandatory", "nfr_security": "mandatory", "config_build": "mandatory"},
    },
    "critical": {
        "title": "Платёжная / Критическая система",
        "matrix": {"vision_c4": "mandatory", "adr": "mandatory", "deployment": "mandatory", "api": "mandatory", "data_model": "mandatory", "nfr_security": "mandatory", "config_build": "mandatory", "threat_model": "mandatory", "drp_bcp": "mandatory"},
    },
    "infra": {
        "title": "Инфраструктурный сервис",
        "matrix": {"vision_c4": "mandatory", "adr": "mandatory", "deployment": "mandatory", "api": "mandatory", "data_model": "optional", "nfr_security": "mandatory", "config_build": "mandatory"},
    },
}

REVIEW_STATUSES = ["draft", "in_review", "changes_requested", "approved"]
LIFECYCLE = ["design", "development", "production", "decommissioned"]
ROLES = ["admin", "domain_expert", "team_lead", "infosec", "viewer"]
COMPONENT_KINDS = ["reference_impl", "shared_lib", "pattern", "boilerplate", "approved_tech", "config_template"]
COMPONENT_STATUSES = ["proposed", "approved", "deprecated", "removed"]

# --- Технический долг (BR-38…40) -------------------------------------------------
# Источник: Confluence dats.tech, space DA (Domain Architecture):
#   - «Реестр технического долга» — pageId=915912594
#   - «Правило генерации идентификатора» — pageId=918365931
#   - «Архитектурный технический долг» — pageId=907535137

DEBT_TYPES = {"AD": "Архитектурный (уровень системы и её устройства)",
              "TD": "Технический (уровень реализации и инженерных практик)"}
DEBT_STATUSES = ["new", "accepted", "planned", "in_progress", "repaid", "cancelled"]
DEBT_STATUS_TITLES = {"new": "Новый", "accepted": "Принят", "planned": "Запланирован",
                      "in_progress": "В работе", "repaid": "Погашен", "cancelled": "Отменён"}
DEBT_RISKS = ["Low", "Medium", "High", "Critical"]
DEBT_PRIORITIES = ["P0", "P1", "P2", "P3"]
# Правило генерации ID: {TYPE}-{ГГГГ}-{ММ}-{NNN}; счётчики AD и TD ведутся
# отдельно, обнуляются ежемесячно; ID неизменяем и не переиспользуется.
