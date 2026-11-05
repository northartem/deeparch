"""Демо-данные: пользователи, компоненты, сервисы (по мотивам реального ландшафта)."""
import itertools
import json
from .auth import hash_password
from .db import exec, q1, q, now
from .standards import ARTIFACT_KINDS, PROJECT_TYPES, CHECKLIST_ITEMS, GRADES

USERS = [  # по одной учётке на каждую роль, пароль у всех 123456
    ("admin",  "Администратор платформы", "admin"),
    ("expert", "Эксперт домена",          "domain_expert"),
    ("lead",   "Тимлид продукта",         "team_lead"),
    ("sec",    "Специалист InfoSec",      "infosec"),
    ("viewer", "Наблюдатель",             "viewer"),
]

DEMO_COMPONENTS = [
    ("Keycloak SSO", "approved_tech", "Стандартная аутентификация (ADR-004): OAuth2/OIDC", "approved", "InfraOPS", "ADR-004", None, "https://gitlab.dats.tech/infra/keycloak"),
    ("ECS Logging Starter", "shared_lib", "Единый стандарт логирования Product Security: ECS, одна строка на событие", "approved", "Observability", "Стандарт логирования", None, "https://gitlab.dats.tech/observability/ecs-logging"),
    ("C4 PlantUML Boilerplate", "boilerplate", "Шаблоны C4 Context/Container + источники dsl/json", "approved", "Architecture", "Vision & C4", None, None),
    ("FastAPI Service Template", "boilerplate", "Референс: CI/CD, healthchecks, .env.example, docker-compose", "approved", "Platform", "ADR-001/002", None, None),
    ("Threat Model Checklist (PCI DSS)", "pattern", "Базовая модель угроз для платёжных систем", "proposed", "InfoSec", "NFR & Security", None, None),
    ("Kafka CDC Naming Policy", "config_template", "Стандарт DNS-записей и наименований Kafka/CDC", "approved", "InfraOPS", "Стандарт наименования DNS", None, None),
]

# Привязка компонентов к сервисам (BR-14: переиспользование)
SERVICE_COMPONENTS = {
    "MPR":  ["Keycloak SSO", "ECS Logging Starter", "FastAPI Service Template"],
    "PCG":  ["Keycloak SSO", "ECS Logging Starter", "Kafka CDC Naming Policy"],
    "UMBB": ["FastAPI Service Template", "C4 PlantUML Boilerplate", "Threat Model Checklist (PCI DSS)"],
}

# CMDB-идентификаторы и источник каталога (BR-20…22)
SERVICE_CMDB = {"MPR": ("CMDB-1042", "backstage"), "PCG": ("CMDB-1187", None), "UMBB": ("CMDB-1210", None)}

DEMO_SERVICES = [
    {"code": "MPR", "name": "MostPartner", "domain": "Payments", "owner": "a.larshin", "architect": "a.larshin", "project_type": "critical", "lifecycle": "production"},
    {"code": "PCG", "name": "Partner Communication Gateway", "domain": "Integrations", "owner": "a.petrov", "architect": "a.petrov", "project_type": "mvp", "lifecycle": "development"},
    {"code": "UMBB", "name": "UMBB", "domain": "Payments", "owner": "a.plyukhin", "architect": "a.plyukhin", "project_type": "b2c_highload", "lifecycle": "design"},
]


DEMO_GROUPS = [
    ("Domain Architecture", "domain", "Команда домена Архитектура (Domain Leads / эксперты)",
     ["expert"], []),
    ("Архитектурный комитет", "committee", "Эскалированные решения и отклонения от стандарта",
     ["expert"], []),
    ("Team Payments", "product", "Продуктовая команда платёжного домена",
     ["lead"], ["MPR", "UMBB"]),
    ("Team Integrations", "product", "Команда интеграционных сервисов",
     [], ["PCG"]),
    ("InfoSec", "security", "Product Security: аудит и комментарии к ревью",
     ["sec"], []),
]


def seed():
    if q1("SELECT id FROM users LIMIT 1"):
        _seed_groups()
        return
    for username, name, role in USERS:
        exec("INSERT INTO users(username, display_name, role, password_hash) VALUES(?,?,?,?)",
             (username, name, role, hash_password("123456")))
    for name, kind, desc, status, team, ref, adr, repo in DEMO_COMPONENTS:
        exec("INSERT INTO components(name, kind, description, status, owner_team, standard_ref, adr_ref, repo_url, created_at)"
             " VALUES(?,?,?,?,?,?,?,?,?)", (name, kind, desc, status, team, ref, adr, repo, now()))
    for s in DEMO_SERVICES:
        sid = exec("INSERT INTO services(code,name,domain,owner,architect,project_type,lifecycle,review_status,created_at,updated_at)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (s["code"], s["name"], s["domain"], s["owner"], s["architect"], s["project_type"], s["lifecycle"], "draft", now(), now()))
        for a in ARTIFACT_KINDS:
            exec("INSERT INTO artifacts(service_id, kind, content_md, diagram_code, version, updated_by, updated_at)"
                 " VALUES(?,?,?,?,?,?,?)",
                 (sid, a["kind"], ARTIFACT_CONTENT.get((s["code"], a["kind"]), ""),
                  DEMO_DIAGRAMS.get((s["code"], a["kind"])), 1,
                  "lead" if ARTIFACT_CONTENT.get((s["code"], a["kind"])) else None,
                  now() if ARTIFACT_CONTENT.get((s["code"], a["kind"])) else None))
        if s["code"] not in CHECKLIST_ANSWERS:   # без предзаполненного прогона стартуем с пустого
            exec("INSERT INTO checklist_runs(service_id, answers, score_pct, mandatory_missing, created_by, created_at)"
                 " VALUES(?,?,?,?,?,?)", (sid, json.dumps([]), 0.0, 0, "system", now()))
    _seed_workflow()
    _seed_groups()


def _seed_workflow():
    """Предзаполненные CMDB, компоненты, self-check и ревью — демо-состояние раздела «Сервисы»."""
    comp_ids = {r["name"]: r["id"] for r in q("SELECT id, name FROM components")}
    # CMDB-идентификаторы и источник каталога
    for code, (cmdb, source) in SERVICE_CMDB.items():
        exec("UPDATE services SET cmdb_id=?, catalog_source=? WHERE code=?", (cmdb, source, code))
    # привязанные компоненты
    for code, names in SERVICE_COMPONENTS.items():
        svc = q1("SELECT id FROM services WHERE code=?", (code,))
        for n in names:
            exec("INSERT OR IGNORE INTO service_components(service_id, component_id) VALUES(?,?)",
                 (svc["id"], comp_ids[n]))
    # прогоны self-check с оценками
    weights = {it["id"]: it["weight"] for it in CHECKLIST_ITEMS}
    for code, (answers, by) in CHECKLIST_ANSWERS.items():
        svc = q1("SELECT id FROM services WHERE code=?", (code,))
        score = sum(GRADES[a["grade"]] for a in answers)
        score_pct = round(100.0 * score / len(CHECKLIST_ITEMS), 1)
        mm = sum(1 for a in answers if weights[a["item_id"]] == "mandatory" and a["grade"] != "E")
        exec("INSERT INTO checklist_runs(service_id,answers,score_pct,mandatory_missing,created_by,created_at)"
             " VALUES(?,?,?,?,?,?)", (svc["id"], json.dumps(answers), score_pct, mm, by, now() - 3600))
    # ревью и статусы жизненного цикла ревью
    for code, req, reviewer, status, comment, hours_ago in DEMO_REVIEWS:
        svc = q1("SELECT id FROM services WHERE code=?", (code,))
        requested_at = now() - hours_ago * 3600
        decided_at = requested_at + 3600 if status != "in_review" else None
        exec("INSERT INTO reviews(service_id,requested_by,requested_at,reviewer,status,comment,decided_at)"
             " VALUES(?,?,?,?,?,?,?)",
             (svc["id"], req, requested_at, reviewer, status, comment, decided_at))
        exec("UPDATE services SET review_status=?, updated_at=? WHERE id=?", (status, now(), svc["id"]))
    # реестр техдолга: ID генерируется по правилу стандарта (счётчики AD/TD отдельно,
    # обнуляются ежемесячно) — вставка в хронологическом порядке регистрации
    from .debts import gen_debt_id
    svc_ids = {r["code"]: r["id"] for r in q("SELECT id, code FROM services")}
    days_ago = itertools.count(start=len(DEMO_DEBTS) * 7, step=-7)   # 35, 28, 21, … дней назад
    for d in DEMO_DEBTS:
        ts = now() - next(days_ago) * 86400
        did = exec(f"INSERT INTO tech_debts(debt_id,dtype,service_id,title,description,cause,"
                   f"arch_decision,target_state,consequences,business_impact,tech_impact,risk,"
                   f"probability,damage,maintenance_cost,repayment_cost,owner,priority,status,"
                   f"review_date,repayment_plan,dependencies,created_by,created_at,updated_at)"
                   f" VALUES({','.join('?' * 25)})",
                   (gen_debt_id(d["dtype"], ts), d["dtype"], svc_ids[d["svc"]], d["title"],
                    d["description"], d["cause"], d["arch_decision"], d["target_state"],
                    d["consequences"], d["business_impact"], d["tech_impact"], d["risk"],
                    d["probability"], d["damage"], d["maintenance_cost"], d["repayment_cost"],
                    d["owner"], d["priority"], d["status"], d["review_date"],
                    d["repayment_plan"], d["dependencies"], d["owner"], ts, ts))


def _seed_groups():
    """Группы доступа: idempotent — дополняет отсутствующие."""
    for name, kind, desc, members, svc_codes in DEMO_GROUPS:
        if q1("SELECT id FROM groups WHERE name=?", (name,)):
            continue
        gid = exec("INSERT INTO groups(name, kind, description) VALUES(?,?,?)", (name, kind, desc))
        for m in members:
            exec("INSERT OR IGNORE INTO group_members(group_id, username) VALUES(?,?)", (gid, m))
        for code in svc_codes:
            svc = q1("SELECT id FROM services WHERE code=?", (code,))
            if svc:
                exec("INSERT OR IGNORE INTO service_grants(group_id, service_id) VALUES(?,?)", (gid, svc["id"]))


# ---------- технический долг: демо-реестр (по мотивам «Реестра технического долга», pageId=915912594) ----------

DEMO_DEBTS = [
    {
        "dtype": "AD", "svc": "MPR", "title": "Синхронная интеграция MPR ↔ 1С",
        "description": "Фискализация уходит синхронным SOAP-вызовом в 1С в транзакции создания выплаты: недоступность 1С блокирует платежи.",
        "cause": "На старте проект требовал мгновенного фискального чека; выбрали самый быстрый вариант интеграции.",
        "arch_decision": "ADR-006 (интеграция с 1С): синхронный SOAP через VPN.",
        "target_state": "Асинхронная очередь: событие payments.events → интеграционный шлюз → 1С, идемпотентный консьюмер.",
        "consequences": "Каскадные отказы при недоступности 1С; выплаты стоят в очереди без статуса.",
        "business_impact": "Простой выплат для партнёров до 40 мин при инцидентах 1С.",
        "tech_impact": "Пулы соединений исчерпываются, ретраи на стороне api.",
        "risk": "High", "probability": 4, "damage": 5,
        "maintenance_cost": "~8 ч/мес на разбор инцидентов и ручные догенерации чеков",
        "repayment_cost": "3–4 спринта (шлюз + идемпотентный консьюмер + сверка)",
        "owner": "expert", "priority": "P0", "status": "in_progress",
        "review_date": "2026-12-01",
        "repayment_plan": "Epic PAY-912 «Асинхронная фискализация»; фаза 1 — очередь, фаза 2 — сверка.",
        "dependencies": "1С:Учёт, команда ERP, инфраструктура Kafka",
    },
    {
        "dtype": "TD", "svc": "MPR", "title": "40% кода сверки без тестов",
        "description": "Модуль settlement покрыт тестами лишь частично: больше половины веток сверки с банком не проверяются автоматически.",
        "cause": "Модуль достался от подрядчика; срочно выводили в прод, тесты отложили.",
        "arch_decision": "Milestone «Production ready» без gate на покрытие.",
        "target_state": "Coverage модуля settlement ≥ 80%, контрактные тесты на сверку.",
        "consequences": "Дорогие и рискованные изменения: каждый релиз сверки — ручной регресс.",
        "business_impact": "Расхождения с банком находят финансы, а не тесты.",
        "tech_impact": "Страх менять код; баги живут до месяцев.",
        "risk": "High", "probability": 4, "damage": 4,
        "maintenance_cost": "~16 ч/мес ручного регресса перед релизами",
        "repayment_cost": "2 спринта",
        "owner": "lead", "priority": "P1", "status": "planned",
        "review_date": "2026-12-15",
        "repayment_plan": "Epic PAY-934 «Тестовый контур сверки».",
        "dependencies": "Тестовый контур банка-эквайера",
    },
    {
        "dtype": "TD", "svc": "PCG", "title": "Ручной деплой dispatcher",
        "description": "Dispatcher доставляется в prod вручную (kubectl apply с ноутбука), api — через CI.",
        "cause": "dispatcher не включили в пайплайн при выделении из монолита.",
        "arch_decision": "Решение о разделении api/dispatcher без пересмотра CI/CD.",
        "target_state": "Единый пайплайн GitLab CI для api и dispatcher, автодеплой в Test, деплой в Prod по тегу.",
        "consequences": "Ошибки при релизах, расхождение версий api и dispatcher.",
        "business_impact": "Задержки доставки уведомлений после инцидентов релиза.",
        "tech_impact": "Нет воспроизводимости, нет отката.",
        "risk": "Medium", "probability": 3, "damage": 3,
        "maintenance_cost": "~2 ч на каждый релиз",
        "repayment_cost": "1 спринт",
        "owner": "expert", "priority": "P2", "status": "accepted",
        "review_date": "2027-01-10",
        "repayment_plan": "Задача INT-407: включить dispatcher в .gitlab-ci.yml.",
        "dependencies": "GitLab CI runners",
    },
    {
        "dtype": "AD", "svc": "UMBB", "title": "Архитектура уровня MVP под целевой RPS 2000",
        "description": "Текущая архитектура (единый api + общая БД без разделения чтения/записи) спроектирована под запуск; целевые 2000 RPS и SLA 99.95% требуют иных решений по масштабированию и отказоустойчивости.",
        "cause": "Стартовый этап проекта: скорость вывода в дизайн важнее целевых NFR.",
        "arch_decision": "ADR-002: монолитный api без разделения деплоя чтения/записи.",
        "target_state": "Разделение контуров чтения/записи, кэш-слой, репликация БД, нагрузочный стенд.",
        "consequences": "Рост p95 под нагрузкой, узкое место в записи транзакций.",
        "business_impact": "Риск невыхода на целевой SLA к запуску маркетинговой кампании.",
        "tech_impact": "Нагрузочное тестирование не проведено, критерии масштабирования не утверждены.",
        "risk": "Critical", "probability": 4, "damage": 5,
        "maintenance_cost": "Растёт с каждым этапом развития (задел под NFR дороже на старте)",
        "repayment_cost": "4–6 спринтов (поэтапно, до production-запуска)",
        "owner": "expert", "priority": "P1", "status": "new",
        "review_date": "2026-12-01",
        "repayment_plan": "Программа «UMBB scale-ready»: NFR-валидация, шардирование кошельков, PAT-стенд.",
        "dependencies": "Team Payments, DBA, инфраструктура",
    },
    {
        "dtype": "TD", "svc": "UMBB", "title": "Нет распределённой трассировки",
        "description": "Сквозной трейсинг клиент → api → PSP → callback не настроен; инциденты разбираются по ECS-логам.",
        "cause": "Трейсинг решили добавить после стабилизации контура депозитов.",
        "arch_decision": "ADR-005: логирование без корреляции между сервисами.",
        "target_state": "OpenTelemetry: трейсы api/PSP/callback, экспорт в общий бэкенд наблюдаемости.",
        "consequences": "Долгое расследование инцидентов платежей.",
        "business_impact": "MTTR платежных инцидентов выше целевого.",
        "tech_impact": "Сложно восстановить путь конкретной транзакции.",
        "risk": "Medium", "probability": 3, "damage": 4,
        "maintenance_cost": "~6 ч/мес на ручную корреляцию логов",
        "repayment_cost": "1 спринт",
        "owner": "sec", "priority": "P2", "status": "planned",
        "review_date": "2026-12-20",
        "repayment_plan": "Задача PAY-941: подключить OTel SDK к api и callback-handler.",
        "dependencies": "Платформа наблюдаемости (Observability)",
    },
]

# Демо-диаграммы UMBB (Mermaid, стандарт: исходники обязательны)
# ---------- предзаполненное содержимое артефактов (демо) ----------

ARTIFACT_CONTENT = {
    # ===== MPR — эталон (critical, production) =====
    ("MPR", "vision_c4"): """## Architecture Vision — MostPartner (MPR)

**Назначение:** платёжный шлюз для партнёров: приём и маршрутизация выплат, расчёты и комиссии.

### 1. Контекст (C4 L1)
- Акторы: Партнёр (B2B), Финансовый контролёр.
- Внешние системы: PSP Gateway, Банк-эквайер, 1С (фискализация), Keycloak SSO.

### 2. Контейнеры (C4 L2)
- **api** (FastAPI) — REST для партнёров, webhooks
- **worker** (Celery) — сверка, ретраи, отчёты
- **db** (PostgreSQL 16) — транзакции, идемпотентность
- **kafka** — payments.events, settlements.events

### 3. Ключевые сценарии
1. Партнёр созда выплату → идемпотентно → PSP → webhook → сверка.
2. Ежедневная сверка с банком; расхождения → очередь разбора.

### 4. Драйверы архитектуры
- Бизнес: SLA 99.95%, PCI DSS, аудируемость операций.
- NFR: 500 RPS (пик), p95 ≤ 300 мс, RTO ≤ 1 ч, RPO ≤ 5 мин.
- Исходники диаграмм: arch/context-diagram.dsl, arch/container-diagram.dsl.""",
    ("MPR", "adr"): """# Каталог ADR — MPR

## ADR-001. Стек
**Контекст:** высоконагруженный платёжный сервис, команда владеет Python.
**Альтернативы:** Java/Spring (команда не владеет), Go (меньше готовых библиотек финансовых интеграций).
**Решение:** Python 3.12 + FastAPI.
**Последствия:** быстрая разработка; GIL компенсируется выносом тяжёлых операций в worker.

## ADR-002. Тип архитектуры
Модульный монолит с явными границами модулей (payments, settlement, reporting), события наружу через Kafka.
**Почему не микросервисы:** команда 6 человек, транзакционная целостность важнее изоляции развёртывания.

## ADR-003. СУБД
PostgreSQL 16. Идемпотентность — unique constraint на external_id + INSERT ON CONFLICT.

## ADR-004. Аутентификация
Keycloak SSO: OAuth2/OIDC для пользователей, mTLS для машинных клиентов (стандарт компании).

## ADR-005. Логирование
ECS Logging Starter: одна строка JSON на событие, сквозной correlation_id (требование Product Security).""",
    ("MPR", "deployment"): """## Deployment — MPR

| Окружение | Конфигурация |
|---|---|
| Dev | docker-compose: api, worker, db, kafka |
| Test | K8s namespace `mpr-test`: api x2, db (1 replica) |
| Prod | K8s cluster `payments`: api x4 (HPA 4–12), worker x2, PostgreSQL Primary + 2 replicas, Redis Sentinel |

Каналы связи: партнёры → WAF → Ingress (TLS 1.3) → api; api → PSP (HTTPS/mTLS через egress-шлюз); api → 1С (VPN, SOAP); сверка с банком — SFTP.""",
    ("MPR", "api"): """## API — MPR (OpenAPI 3.1: openapi.yaml в репозитории)

### POST /v1/payouts
Создание выплаты. Заголовок `Idempotency-Key` обязателен.
Ответы: 201 (создана), 409 (дубликат по ключу), 422 (валидация).

### GET /v1/payouts/{id}
Статус выплаты: pending | settled | failed + таймлайн событий.

### POST /v1/payouts/{id}/cancel
Отмена в статусе pending. JWT scope `payouts:write`, только владелец.

### События (AsyncAPI)
Kafka topic `payments.events`: payout.settled, payout.failed. Ключ = payout_id, формат CloudEvents 1.0.""",
    ("MPR", "data_model"): """## Модель данных — MPR (er-diagram.dbml в репозитории)

- **PARTNER**(id, inn, name, status) — владелец: MPR
- **PAYOUT**(id, partner_id FK, external_id UK, amount, currency, status, created_at)
- **PAYOUT_EVENT**(id, payout_id FK, event_type, payload JSONB, at) — append-only, аудит
- **SETTLEMENT**(id, date, partner_id FK, amount, reconciled)

Правила: денежные суммы — `NUMERIC(18,2)`, без float; PII (инн) маскируется в логах; имена топиков/полей — по стандарту Kafka CDC Naming Policy.""",
    ("MPR", "nfr_security"): """## NFR & Security profile — MPR

- Пропускная способность: 500 RPS (пик), 150 RPS (среднее)
- Задержка: p95 ≤ 300 мс (создание выплаты), p99 ≤ 800 мс
- Доступность: 99.95% (SLA), деплой без окна (rolling)
- Масштабирование: HPA по CPU и глубине очереди
- Модель угроз: PCI DSS, STRIDE-анализ (Threat Model), данные карт не хранятся — токенизация на стороне PSP
- Шифрование: TLS 1.3 наружу, mTLS к PSP, AES-256 at rest
- Наблюдаемость: Prometheus, OpenTelemetry, ECS-логи
- DR: RPO ≤ 5 мин (WAL-архив), RTO ≤ 1 ч (план DRP-2024-07)""",
    ("MPR", "config_build"): """## Config & Build — MPR

- `docker-compose.yml` — полный стенд одной командой `docker compose up` (api, worker, db, kafka, keycloak-mock)
- `.env.example` — все переменные с описанием; секреты только через Vault
- CI: lint (ruff) → тесты (pytest, coverage ≥ 80%) → build → автодеплой в Test, в Prod — по тегу с ручным подтверждением
- Миграции: Alembic, обратная совместимость на 1 релиз""",
    # ===== PCG — в работе (mvp, development) =====
    ("PCG", "vision_c4"): """## Architecture Vision — Partner Communication Gateway (PCG)

**Назначение:** единая точка доставки уведомлений партнёрам: email, SMS, push, webhook — с ретраями и шаблонами.

### 1. Контекст (C4 L1)
- Акторы: Продуктовые команды (отправители), Партнёр (получатель).
- Внешние системы: SMTP-провайдер, SMS-шлюз.

### 2. Контейнеры (C4 L2)
- **api** (FastAPI) — приём заявок, шаблоны, статусы
- **dispatcher** (worker) — доставка, ретраи, DLQ
- **db** (PostgreSQL) — заявки, шаблоны, попытки доставки

### 3. Ключевые сценарии
1. Команда публикует событие в Kafka `pcg.send` → dispatcher доставляет по каналу, 3 ретрая с экспоненциальной паузой.
2. Webhook партнёру — подпись HMAC, TTL 30 с.

### 4. Драйверы архитектуры
- NFR: 50 RPS приём, p95 ≤ 500 мс, доставка ≤ 60 с
- SLA доставки: 99% за 5 минут""",
    ("PCG", "adr"): """# Каталог ADR — PCG

## ADR-001. Стек
Python 3.12 + FastAPI (референс FastAPI Service Template).

## ADR-002. Тип архитектуры
Один сервис + dispatcher-процесс; событийный вход через Kafka.

## ADR-003. СУБД
PostgreSQL 15: заявки и статусы доставки; ретраи через таблицу outbox.

## ADR-004. Аутентификация
Keycloak SSO; service-accounts для продюсеров Kafka (SASL/TLS).

## ADR-005. Логирование
ECS Logging Starter, correlation_id = id заявки; PII получателей маскируется.""",
    ("PCG", "deployment"): """## Deployment — PCG

- **Dev:** docker-compose (api, dispatcher, db, kafka)
- **Prod:** K8s namespace `integrations`: api x2, dispatcher x2, PostgreSQL (managed)

Каналы: продюсеры → Kafka (TLS/SASL) → dispatcher → внешние провайдеры (HTTPS).""",
    ("PCG", "api"): """## API — PCG

### POST /v1/messages
Тело: `{channel, template_id, recipient, params}`. Ответ 202 + id заявки.

### GET /v1/messages/{id}
Статус: queued | sent | delivered | failed + история попыток.

### GET /v1/templates
Шаблоны уведомлений (версии неизменяемы).

### События
Kafka `pcg.send` (вход), `pcg.status` (выход: delivered / failed).""",
    ("PCG", "data_model"): """## Модель данных — PCG

- **MESSAGE**(id, channel, template_id FK, recipient, params JSONB, status, attempts, next_retry_at)
- **TEMPLATE**(id, name, version, body, locale) — версия неизменяема
- **DELIVERY_ATTEMPT**(id, message_id FK, at, result, error)

Соглашения: snake_case, таблицы в единственном числе (стандарт наименования БД).""",
    ("PCG", "nfr_security"): """## NFR & Security — PCG

- 50 RPS приём, доставка ≤ 60 с (p95), ретраи: 3 попытки / 10 мин
- Доступность 99.5%
- Модель угроз: подмена webhook (HMAC-подпись с TTL), утечка PII в шаблонах (маскирование в логах)
- Персональные данные получателей не хранятся дольше 90 дней (ретеншн)""",
    ("PCG", "config_build"): """## Config & Build — PCG

- `docker-compose.yml` — api + dispatcher + db + kafka одной командой
- `.env.example` — SMTP_*, SMS_*, KAFKA_*
- CI: pytest → build → автодеплой в Test; в Prod — вручную""",
    # ===== UMBB — в проектировании (b2c_highload, design) =====
    ("UMBB", "vision_c4"): """## Architecture Vision — UMBB

**Назначение:** высоконагруженная платёжная B2C-платформа: депозиты и выводы для игроков.

### 1. Контекст (C4 L1)
Акторы: Игрок, Оператор поддержки. Внешние системы: PSP Gateway, KYC Provider.
Диаграмма и исходник — вкладка «Диаграммы» (context-diagram.dsl).

### 2. Контейнеры (C4 L2)
- **api** (FastAPI) — REST, идемпотентность операций
- **PostgreSQL 16** — кошельки и транзакции
- **Redis** — сессии и блокировки идемпотентности

### 3. Ключевые сценарии
1. Депозит: игрок → api → PSP → webhook → подтверждение.
2. Вывод: KYC-проверка → резервирование → PSP.

### 4. Драйверы архитектуры
- NFR: 2000 RPS (пик), p95 ≤ 200 мс, SLA 99.95%
- Безопасность: KYC, AML-триггеры, PCI DSS SAQ-D""",
    ("UMBB", "adr"): """# Каталог ADR — UMBB

## ADR-001. Стек
Python 3.12 + FastAPI. **Альтернативы:** Go (скорость разработки команды ниже), Java/Spring.
**Последствия:** асинхронный FastAPI + uvloop держит целевой RPS.

## ADR-002. Тип архитектуры
Сервис-ориентированный: api и callback-handler — отдельные деплойменты, общая БД.
**Почему не монолит:** разные профили нагрузки (чтение против записи транзакций).

## ADR-003. СУБД
PostgreSQL 16 + Redis для идемпотентности (SETNX с TTL).
**Альтернатива:** только PostgreSQL — медленнее под 2000 RPS на блокировках.

## ADR-004. Аутентификация
Keycloak SSO для операторов; игроки — delegated JWT партнёра.

## ADR-005. Логирование
ECS Logging Starter; PII (email) маскируется на выходе.""",
    ("UMBB", "deployment"): """## Deployment — UMBB

- **Dev:** docker-compose (api, callback-handler, db, redis)
- **Prod (план):** K8s: api x4 (HPA 4–16), PostgreSQL Primary + 2 replicas, Redis

Диаграмма Deployment (C4) и исходник — вкладка «Диаграммы».""",
    ("UMBB", "api"): """## API — UMBB

### POST /v1/deposits
Идемпотентность: заголовок `Idempotency-Key` → Redis SETNX.
Схема потока — вкладка «Диаграммы» (flowchart).

### GET /v1/transactions/{id}
Статус и таймлайн операции.

### POST /v1/withdrawals
Требует `kyc_status=verified`.

OpenAPI 3.1: openapi.yaml (черновик, 3 эндпоинта).""",
    ("UMBB", "data_model"): """## Модель данных — UMBB

Сущности: PLAYER, WALLET, TRANSACTION (erDiagram — вкладка «Диаграммы»).
- Денежные поля `NUMERIC(18,2)`
- TRANSACTION — append-only, статусная машина: pending → done | failed
- WALLET.balance — консистентность через транзакцию БД
Соглашения об именовании: snake_case (стандарт БД).""",
    ("UMBB", "nfr_security"): """## NFR & Security profile — UMBB

- Целевой RPS: 2000 (пик), p95 ≤ 200 мс — **оценка, нагрузочное тестирование не проведено**
- SLA 99.95%
- Модель угроз: базовая (PCI DSS SAQ-D, KYC/AML) — требуется детализация по STRIDE
- Масштабирование: HPA по CPU — критерии срабатывания не утверждены""",
    ("UMBB", "config_build"): "",
}

# ---------- self-check: предзаполненные прогоны ----------
# Правило стандарта: оценка без ссылки опускается до «Ч» — это отражено в ответах.

CHECKLIST_ANSWERS = {
    "MPR": ([  # эталон: всё E со ссылками → 100%, гейт пройден
        {"item_id": 1,  "grade": "E", "link": "https://confluence.dats.tech/display/PAY/MPR-context"},
        {"item_id": 2,  "grade": "E", "link": "https://confluence.dats.tech/display/PAY/MPR-containers"},
        {"item_id": 3,  "grade": "E", "link": "https://confluence.dats.tech/display/PAY/MPR-deployment"},
        {"item_id": 4,  "grade": "E", "link": "https://gitlab.dats.tech/payments/mpr/-/tree/master/adr"},
        {"item_id": 5,  "grade": "E", "link": "https://gitlab.dats.tech/payments/mpr/-/blob/master/adr/ADR-004-auth.md"},
        {"item_id": 6,  "grade": "E", "link": "https://gitlab.dats.tech/payments/mpr/-/blob/master/api/openapi.yaml"},
        {"item_id": 7,  "grade": "E", "link": "https://gitlab.dats.tech/payments/mpr/-/blob/master/db/er-diagram.dbml"},
        {"item_id": 8,  "grade": "E", "link": "https://confluence.dats.tech/display/PAY/MPR-nfr"},
        {"item_id": 9,  "grade": "E", "link": "https://gitlab.dats.tech/payments/mpr/-/blob/master/docker-compose.yml"},
        {"item_id": 10, "grade": "E", "link": "https://confluence.dats.tech/display/PAY/MPR-card"},
    ], "lead"),
    "PCG": ([  # готово к ревью: 95%, необязательный пункт «частично»
        {"item_id": 1,  "grade": "E", "link": "https://confluence.dats.tech/display/INT/PCG-context"},
        {"item_id": 2,  "grade": "E", "link": "https://confluence.dats.tech/display/INT/PCG-containers"},
        {"item_id": 3,  "grade": "E", "link": "https://confluence.dats.tech/display/INT/PCG-deployment"},
        {"item_id": 4,  "grade": "E", "link": "https://gitlab.dats.tech/integrations/pcg/-/tree/main/adr"},
        {"item_id": 5,  "grade": "E", "link": "https://gitlab.dats.tech/integrations/pcg/-/blob/main/adr/ADR-004-auth.md"},
        {"item_id": 6,  "grade": "E", "link": "https://gitlab.dats.tech/integrations/pcg/-/blob/main/api/openapi.yaml"},
        {"item_id": 7,  "grade": "E", "link": "https://gitlab.dats.tech/integrations/pcg/-/blob/main/db/schema.dbml"},
        {"item_id": 8,  "grade": "E", "link": "https://confluence.dats.tech/display/INT/PCG-nfr"},
        {"item_id": 9,  "grade": "Ch", "link": ""},
        {"item_id": 10, "grade": "E", "link": "https://confluence.dats.tech/display/INT/PCG-card"},
    ], "expert"),
    "UMBB": ([  # в работе: 2 блокера (3 — deployment без ссылки, 6 — API частично) → гейт не пропускает
        {"item_id": 1,  "grade": "E", "link": "https://confluence.dats.tech/display/PAY/UMBB-context"},
        {"item_id": 2,  "grade": "E", "link": "https://confluence.dats.tech/display/PAY/UMBB-containers"},
        {"item_id": 3,  "grade": "Ch", "link": ""},
        {"item_id": 4,  "grade": "E", "link": "https://gitlab.dats.tech/payments/umbb/-/tree/develop/adr"},
        {"item_id": 5,  "grade": "E", "link": "https://gitlab.dats.tech/payments/umbb/-/blob/develop/adr/ADR-004-auth.md"},
        {"item_id": 6,  "grade": "Ch", "link": ""},
        {"item_id": 7,  "grade": "E", "link": "https://gitlab.dats.tech/payments/umbb/-/blob/develop/db/er-diagram.dbml"},
        {"item_id": 8,  "grade": "Ch", "link": ""},
        {"item_id": 9,  "grade": "N", "link": ""},
        {"item_id": 10, "grade": "E", "link": "https://confluence.dats.tech/display/PAY/UMBB-card"},
    ], "lead"),
}

# ---------- ревью: предзаполненные ----------
DEMO_REVIEWS = [
    # (код, requested_by, reviewer, статус, комментарий, запрошено_часов_назад)
    ("MPR", "lead",   "expert", "approved",
     "Эталонное оформление: C4 с исходниками, полный ADR-каталог, NFR с цифрами, DR-план. Принято без замечаний.", 72),
    ("PCG", "expert", None, "in_review", None, 4),
]

DEMO_DIAGRAMS = {
    ("MPR", "vision_c4"): """C4Context
      title System Context — MPR (C4 Level 1)
      Person(partner, "Партнёр", "B2B-клиент платформы Most")
      Person(fin, "Финансовый контролёр", "Финансы")
      System(mpr, "MostPartner", "Платёжный шлюз: выплаты и расчёты")
      System_Ext(psp, "PSP Gateway", "Внешний платёжный провайдер")
      System_Ext(bank, "Банк-эквайер", "Расчёты и выписки")
      System_Ext(erp, "1С", "Фискализация и учёт")
      Rel(partner, mpr, "Запрашивает выплаты", "HTTPS/OIDC")
      Rel(fin, mpr, "Контроль расчётов", "HTTPS")
      Rel(mpr, psp, "Проведение выплат", "HTTPS/mTLS")
      Rel(mpr, bank, "Сверка и выписки", "SFTP")
      Rel(mpr, erp, "Фискальные документы", "SOAP/VPN")""",
    ("MPR", "deployment"): """C4Deployment
      title Deployment — MPR (Prod)
      Deployment_Node(cluster, "Payments Cluster", "Kubernetes") {
        Deployment_Node(apiPool, "api-pool", "x4 pods (HPA 4–12)") {
          Container(api, "MPR API", "FastAPI", "REST, webhooks")
        }
        Deployment_Node(workers, "worker-pool", "x2 pods") {
          Container(wrk, "MPR Worker", "Celery", "Сверка, ретраи")
        }
        Deployment_Node(dbPool, "db-pool", "Primary + 2 replicas") {
          ContainerDb(db, "PostgreSQL", "16", "Транзакции и расчёты")
        }
      }
      System_Ext(psp, "PSP Gateway", "Внешний провайдер")
      Rel(api, db, "Транзакции", "TCP 5432")
      Rel(wrk, db, "Сверка", "TCP 5432")
      Rel(api, psp, "Выплаты", "HTTPS/mTLS")""",
    ("PCG", "vision_c4"): """C4Context
      title System Context — PCG (C4 Level 1)
      Person(sender, "Продуктовая команда", "Отправитель уведомлений")
      Person(partner, "Партнёр", "Получатель")
      System(pcg, "Partner Communication Gateway", "Доставка уведомлений: email, SMS, push, webhook")
      System_Ext(smtp, "SMTP-провайдер", "Email-рассылки")
      System_Ext(sms, "SMS-шлюз", "SMS-доставка")
      Rel(sender, pcg, "Публикует заявку на отправку", "Kafka pcg.send")
      Rel(pcg, smtp, "Email", "HTTPS")
      Rel(pcg, sms, "SMS", "HTTPS")
      Rel(pcg, partner, "Webhook-уведомления", "HTTPS/HMAC")""",
    ("PCG", "api"): """flowchart LR
      P[Продюсер] -->|Kafka pcg.send| D[Dispatcher]
      D -->|шаблон| T[(PostgreSQL: templates)]
      D -->|email| SMTP[SMTP-провайдер]
      D -->|sms| SMS[SMS-шлюз]
      D -->|webhook + HMAC| W[Партнёрский endpoint]
      D -.ретрай 1м/5м/30м.-> D
      D -->|Kafka pcg.status| ST[Статусы доставки]""",
    ("UMBB", "vision_c4"): """C4Context
      title System Context — UMBB (C4 Level 1)
      Person(player, "Игрок", "B2C клиент платформы")
      Person(admin, "Оператор", "Служба поддержки платежей")
      System(umbb, "UMBB", "Платёжная платформа: депозиты и выводы")
      System_Ext(psp, "PSP Gateway", "Внешний платёжный провайдер")
      System_Ext(kyc, "KYC Provider", "Проверка личности")
      Rel(player, umbb, "Вносит депозит / запрашивает вывод", "HTTPS")
      Rel(admin, umbb, "Модерация операций", "HTTPS")
      Rel(umbb, psp, "Проведение платежей", "HTTPS/mTLS")
      Rel(umbb, kyc, "Верификация игрока", "HTTPS")""",
    ("UMBB", "deployment"): """C4Deployment
      title Deployment — UMBB (Prod)
      Deployment_Node(prod, "Prod Cluster", "Kubernetes") {
        Deployment_Node(api, "api-pool", "x4 pods") {
          Container(apiSvc, "UMBB API", "FastAPI", "REST/gRPC")
        }
        Deployment_Node(db, "db-pool", "Primary + 2 replicas") {
          ContainerDb(dbMain, "PostgreSQL", "16", "Транзакции и кошельки")
        }
        Container(cache, "Redis", "Кэш сессий и идемпотентность")
      }
      System_Ext(psp, "PSP Gateway", "Внешний провайдер")
      Rel(apiSvc, dbMain, "Чтение/запись", "TCP 5432")
      Rel(apiSvc, cache, "Кэш", "TCP 6379")
      Rel(apiSvc, psp, "Платежи", "HTTPS/mTLS")""",
    ("UMBB", "data_model"): """erDiagram
      PLAYER ||--o{ WALLET : owns
      PLAYER ||--o{ TRANSACTION : makes
      WALLET ||--o{ TRANSACTION : debits
      TRANSACTION {
        bigint id PK
        string type "deposit|withdraw"
        decimal amount
        string status "pending|done|failed"
        timestamp created_at
      }
      PLAYER {
        bigint id PK
        string email UK
        string kyc_status
      }
      WALLET {
        bigint id PK
        bigint player_id FK
        string currency
        decimal balance
      }""",
    ("UMBB", "api"): """flowchart LR
      Client[Frontend / Партнёр] -->|POST /v1/deposits| GW[API Gateway]
      GW -->|validate + idempotency| DEP[Deposit Service]
      DEP -->|reserve| DB[(PostgreSQL)]
      DEP -->|charge| PSP[PSP Gateway]
      PSP -->|webhook callback| CB[Callback Handler]
      CB -->|confirm| DB
      CB -->|event: deposit.done| K[Kafka: payments.events]""",
}


def demo_vision_template(service_name: str) -> str:
    m = PROJECT_TYPES.get(service_name)
    return f"""## Architecture Vision — {service_name or "<сервис>"}

### 1. Контекстная диаграмма (C4 Level 1)
<!-- Система как «чёрный ящик» + внешние акторы. Исходник: context-diagram.dsl -->

### 2. Container Diagram (C4 Level 2)
<!-- Компоненты, границы, связи. Исходник: container-diagram.dsl -->

### 3. Ключевые бизнес-сценарии
1. ...

### 4. Драйверы архитектуры
- Бизнес-цели: ...
- NFR: RPS ..., SLA ..., безопасность: ...
"""
