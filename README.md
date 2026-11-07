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
| AI-ускорение | BR-27…37 | адаптер AI (mock → AI-Buddy): AI-черновики артефактов, AI-ревью пакета до отправки (двухслойное: формальные проверки + LLM-проход, advisory), human-in-the-loop |
| Модуль техдолга | BR-38…40 | реестр AD/TD по стандарту DA (Confluence pageId=915912594, 918365931, 907535137): ID `{AD\|TD}-{ГГГГ}-{ММ}-{NNN}`, риск = вероятность × ущерб (Ds), P0–P3, статусы Новый→Погашен, владелец, стоимость, план погашения |
| Дашборд и аудит | — | покрытие, статусы ревью, использование компонентов, журнал действий |

Данные стандарта захардкожены из реальных страниц Confluence: `app/standards.py`
(7 артефактов, чек-лист self-check, матрица 6 типов проектов).

## Что реализовано (MVP2)

| Модуль | BR | Что делает |
| --- | --- | --- |
| Fitness functions | BR-41…44 | правила-фитнес-функции над артефактами (исходники диаграмм, 3+ эндпоинта API, NFR в цифрах, ADR-001…005, docker compose); прогон с вердиктом pass/fail/warn; экспорт CI-пака (gitlab-ci + автономный python-скрипт) для проверки в репозитории |
| Service Factory | BR-45…47 | скаффолдинг: сервис + 7 артефактов по шаблонам стандарта + пустой self-check + подключение approved-компонентов + отчёт next_steps по матрице типа проекта |
| AI-ассистент | BR-48…50 | генерация ответов корпоративной LLM (AI-Buddy, OpenAI-совместимый контракт, env: `AI_BUDDY_URL`/`AI_BUDDY_TOKEN`/`AI_BUDDY_MODEL`) поверх базы знаний из реальных страниц Confluence (pageId=894079737, 918379090, 924778815, 913365280, 915912594, 918365931, 907535137); цитаты pageId/url; без LLM — fallback на извлекающий ответ |
| NFR-валидация | BR-51…53 | извлечение целей (RPS, p95, SLA, RTO, RPO) из артефакта NFR regex'ами; факт по метрикам; статус ok / breach / unknown с вердиктом по сервису |
| Синхронизация с Confluence | BR-54…56 | экспорт реестра долга в XHTML (storage format, pageId=915912594); импорт markdown-таблицы с сохранением ID (ID неизменяем — pageId=918365931) |

## Структура

```
app/
  main.py          # FastAPI, статика SPA
  api.py           # REST API (/api)
  db.py            # SQLite (WAL)
  standards.py     # данные Architecture Definition Set
  ai.py            # AI-адаптер (mock → AI-Buddy)
  integrations.py  # адаптер каталога/CMDB + синхронизация с Confluence
  fitness.py       # fitness-функции + генерация CI-пака
  factory.py       # Service Factory (скаффолдинг)
  kb.py/kb_data.py # AI-ассистент: ретрив по базе знаний (реальные страницы) + генерация LLM
  llm.py           # клиент корпоративной LLM (AI-Buddy, OpenAI-совместимый)
  nfr.py           # NFR-валидация: извлечение целей, цель vs факт
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
POST /api/ai/draft                        → AI-черновик (AI-Buddy + KB, fallback шаблон)
POST /api/services/{id}/ai-review         → AI-ревью пакета до отправки (формальный слой + LLM, advisory)
GET  /api/services/{id}/ai-review         → последний прогон AI-ревью (null, если не было)
POST /api/ai/precheck                     → 410: AI Gate упразднён, поглощён AI-ревью
POST /api/services/{sid}/artifacts/scaffold → скелеты обязательных артефактов (которых ещё нет)
GET/POST /api/services/{sid}/requirements   → реестр ФТ/НФТ на сервисе (трассировка covered_by)
POST /api/services/{sid}/requirements/parse → AI-разбор вставленного документа на требования
POST /api/services/{sid}/requirements/import → импорт разобранного (номера ФТ-N/НФТ-N)
PATCH/DELETE /api/requirements/{id}         → правка/удаление требования
POST /api/services/{sid}/nfr/from-requirements → черновик NFR profile из НФТ
GET/PUT /api/services/{sid}/c4[/{view}]     → визуальные C4-модели (context L1 / container L2)
POST /api/services/{sid}/c4/{view}/ai       → AI-структура C4-модели (advisory)
POST /api/services/{sid}/c4/export          → экспорт моделей в Mermaid-исходник Vision (dry_run — предпросмотр)
POST /api/integrations/backstage/import  → импорт из каталога (dry-run)
GET  /api/integrations/services/{id}/catalog-export → catalog-info.yaml
GET/POST /api/debts … /api/debts/{id}/status → реестр техдолга (BR-38…40)
GET  /api/fitness/rules                  → активные fitness-правила
POST /api/services/{id}/fitness          → прогон fitness-проверок
GET  /api/services/{id}/fitness/ci.txt   → CI-пак (gitlab-ci + python)
POST /api/factory/scaffold               → Service Factory (BR-45…47)
POST /api/assistant                      → AI-ассистент с цитатами (BR-48…50)
POST /api/assistant/stream               → стриминг ответа (SSE: meta → delta* → done)
GET  /api/assistant/status               → провайдер LLM + размер базы знаний
GET  /api/assistant/models               → список моделей для селектора в чате
GET  /api/assistant/chats                → список чатов пользователя (левая панель)
DELETE /api/assistant/chats/{id}         → удалить чат с историей
GET/DELETE /api/assistant/history        → сообщения чата (?chat_id=) / очистка всех чатов
POST /api/services/{id}/nfr/extract      → извлечь NFR-цели из артефакта
PATCH /api/nfr/{mid}                     → факт по метрике + вердикт
POST /api/integrations/confluence/export|import → XHTML экспорт / markdown импорт долга
GET  /api/dashboard | /api/audit
```

## Дорожная карта (следующие шаги)

1. **AI-Buddy для остальных AI-сценариев** — AI-черновики, разбор требований и AI-ревью пакета
   (`app/ai_review.py`) уже ходят в корпоративную LLM (`app/ai.py`, `app/reqs.py` → `app/llm.py`,
   `reasoning_effort=low`).
2. **Real Confluence API** — прямая запись XHTML на страницу реестра долга (сейчас — копипаста через UI).
3. **Backstage-коннектор** — реальный `catalog-info.yaml` из GitLab вместо mock.
4. **DataGerry-коннектор** — ObjectTypes + матрица доступов (контур ИБ).
5. Impact analysis по графу зависимостей CMDB (BR-24), контекст ревью из CMDB (BR-25).
6. Диаграммы: редактор C4 (Mermaid/Structurizr DSL) с хранением исходников.
7. Переход с токенов на SSO/LDAP компании.
