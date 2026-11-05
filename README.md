# DeepArch MVP

Клиент-серверная ИС для проектирования, изменения и **ревью архитектуры сервисов** на базе
корпоративного стандарта **Architecture Definition Set** (Confluence, pageId=894079737).

## Запуск

```bash
uv run uvicorn app.main:app --port 8731
# открыть http://localhost:8731
```

Стек: **FastAPI + SQLite + vanilla JS SPA**. Без внешних сервисов; БД создаётся и наполняется демо-данными автоматически.

## Демо-пользователи (токен предвыдан)

| Логин | Роль | Что может |
|---|---|---|
| `admin` | admin | всё + управление доступом + аудит |
| `expert` | domain_expert | решения по ревью (или через Архитектурный комитет), каталог компонентов, интеграции |
| `lead` | team_lead | карточки/артефакты/self-check/ревью **своих** сервисов (Team Payments: MPR, UMBB) |
| `sec` | infosec | просмотр всего + журнал аудита |
| `viewer` | viewer | только просмотр |

Пароль у всех демо-учёток: `123456`. Аутентификация: `POST /api/login {username, password}` → сессионный токен (PBKDF2-SHA256, TTL 7 дней), далее заголовок `X-Token`.

Управление: вкладка **«Доступ»** — роли, группы (domain / committee / product / security), гранты «группа → сервисы».
Доступ к сервису = domain_expert/admin ИЛИ product-группа с грантом ИЛИ owner/architect в карточке.

## Что реализовано (MVP)

| Домен | Требования | Реализация |
|---|---|---|
| Реестр сервисов и карточки | BR-01 | `/services`, карточка: владелец, архитектор, домен, тип проекта, жизненный цикл, CMDB ID |
| Архитектурный пакет (7 артефактов) | BR-02 | Vision+C4, ADR, Deployment, API, Data Model, NFR&Security, Config&Build — по шаблонам стандарта, версионирование, ссылка на исходник |
| Self-check со скорингом | BR-03 | 10 пунктов Е/Ч/Н, правило «нет ссылки → не «Есть»», порог «все обязательные = E» |
| Workflow ревью | BR-04/05 | draft → in_review → approved / changes_requested; gate: self-check без блокеров; решение только у domain_expert |
| Каталог переиспользуемых компонентов | BR-14…19 | билдинг-блоки со статусами proposed/approved/deprecated, связь со стандартом/ADR, использование, compliance by construction |
| Интеграция с каталогом/CMDB | BR-20…23 | адаптер `CatalogAdapter`: mock Backstage (import/export catalog-info.yaml), слот для DataGerry (REST) |
| AI-ускорение | BR-27…37 | адаптер AI (mock → AI-Buddy): AI-черновики артефактов, AI Gate предсказание self-check с evidence, advisory-режим, human-in-the-loop |
| Модуль техдолга | BR-38…40 | реестр AD/TD по стандарту DA (Confluence pageId=915912594, 918365931, 907535137): ID `{AD\|TD}-{ГГГГ}-{ММ}-{NNN}`, риск = вероятность × ущерб (Ds), P0–P3, статусы Новый→Погашен, владелец, стоимость, план погашения |
| Дашборд и аудит | — | покрытие, статусы ревью, использование компонентов, журнал действий |

Данные стандарта захардкожены из реальных страниц Confluence: `app/standards.py`
(7 артефактов, чек-лист self-check, матрица 6 типов проектов).

## Структура

```
app/
  main.py          # FastAPI, статика SPA
  api.py           # REST API (/api)
  db.py            # SQLite (WAL)
  standards.py     # данные Architecture Definition Set
  ai.py            # AI-адаптер (mock → AI-Buddy)
  integrations.py  # адаптер каталога/CMDB (mock Backstage → DataGerry)
  auth.py          # токены + RBAC
  seed.py          # демо-данные
web/               # SPA: index.html, app.js, styles.css
```

## API (кратко)

```
POST /api/login                          → токен
GET  /api/standard                       → артефакты, чек-лист, матрица типов
GET/POST/PATCH /api/services[/{id}]      → реестр и карточки
PUT  /api/services/{id}/artifacts/{kind} → сохранить артефакт (версия +1)
POST /api/services/{id}/checklist        → self-check (скор, блокеры, вердикт)
POST /api/services/{id}/reviews          → на ревью (gate по self-check)
POST /api/reviews/{id}/decision          → approved | changes_requested (expert+)
GET/POST /api/components                 → каталог компонентов
POST /api/services/{id}/components       → подключить компонент
POST /api/ai/draft | /api/ai/precheck    → AI-черновик / AI Gate (advisory)
POST /api/integrations/backstage/import  → импорт из каталога (dry-run)
GET  /api/integrations/services/{id}/catalog-export → catalog-info.yaml
GET  /api/dashboard | /api/audit
```

## Дорожная карта (следующие шаги)

1. **AI-Buddy вместо mock** — реализовать провайдера за тем же контрактом API.
2. **Backstage-коннектор** — реальный `catalog-info.yaml` из GitLab вместо mock.
3. **DataGerry-коннектор** — ObjectTypes + матрица доступов (контур ИБ).
4. Impact analysis по графу зависимостей CMDB (BR-24), контекст ревью из CMDB (BR-25).
5. Диаграммы: редактор C4 (Mermaid/Structurizr DSL) с хранением исходников.
6. Переход с токенов на SSO/LDAP компании.
