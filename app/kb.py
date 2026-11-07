"""RAG-ассистент (MVP2 BR-48…50): LLM-генерация поверх двух источников.

Контекст двухслойный:
  1) база знаний стандарта — страницы Confluence dats.tech (kb_data.py), чанки + TF-IDF;
  2) данные платформы DeepArch — реестр ИС (всегда) и глубокий контекст конкретного
     сервиса (чип из карточки ИЛИ упоминание имени/кода сервиса в вопросе):
     карточка, требования, компоненты, контент артефактов, C4-модели, техдолг, ревью.
Ответ генерирует корпоративная LLM (AI-Buddy, app/llm.py) строго по извлечённому
контексту; если LLM не сконфигурирована/недоступна — извлекающий ответ из тех же
источников. В обоих режимах возвращаются цитаты и режим advisory: ассистент только
отвечает, ничего не меняет (BR-33).
"""
import json
import math
import re
import threading

from . import llm, roles
from .db import q, q1
from .kb_data import PAGES
from .standards import ARTIFACT_KINDS

_CHUNK = 900


def _split_sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) > 30]


def _chunks():
    out = []
    for p in PAGES:
        text = p["text"]
        # режем по абзацам, склеивая до ~_CHUNK символов
        paras = [t.strip() for t in text.split("\n\n") if t.strip()]
        cur = ""
        for para in paras:
            if cur and len(cur) + len(para) > _CHUNK:
                out.append({**p, "chunk": cur}); cur = ""
            cur = (cur + "\n\n" + para).strip()
        if cur:
            out.append({**p, "chunk": cur})
    return out


CHUNKS = _chunks()
_VOCAB: dict[str, int] = {}
_DA_KEY: tuple | None = None
_DA_CHUNKS: list[dict] = []
_DA_LOCK = threading.Lock()   # sync-ручки FastAPI идут в threadpool — перестройка под локом


def _tokenize(text):
    return [t for t in re.findall(r"\w{3,}", text.lower())]


def _vector(tokens):
    tf = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    return tf


def _rebuild_idf():
    global _IDF
    df = {}
    for c in CHUNKS + _DA_CHUNKS:
        for t in set(_tokenize(c["chunk"])):
            df[t] = df.get(t, 0) + 1
    n = len(CHUNKS) + len(_DA_CHUNKS)
    _IDF = {t: math.log(n / (1 + k)) + 1.0 for t, k in df.items()}


_rebuild_idf()   # начальный IDF по KB-чанкам (чанки сервисов добавляются лениво)


def _da_key() -> tuple:
    """Сигнатура данных DeepArch для инвалидации индекса: счётчики + MAX(id)/MAX(updated_at)
    по всем таблицам, чьи данные попадают в чанки. COUNT/MAX(id) ловят и удаления,
    у таблиц без updated_at (checklist_runs, components) — только они."""
    r = q1("""SELECT (SELECT COUNT(*) FROM services) AS a,
                     (SELECT MAX(id) FROM services) AS b,
                     (SELECT MAX(updated_at) FROM services) AS c,
                     (SELECT COUNT(*) FROM artifacts) AS d,
                     (SELECT MAX(id) FROM artifacts) AS e,
                     (SELECT MAX(updated_at) FROM artifacts) AS f,
                     (SELECT COUNT(*) FROM requirements) AS g,
                     (SELECT MAX(id) FROM requirements) AS h,
                     (SELECT MAX(updated_at) FROM requirements) AS i,
                     (SELECT COUNT(*) FROM tech_debts) AS j,
                     (SELECT MAX(id) FROM tech_debts) AS k,
                     (SELECT COUNT(*) FROM c4_models) AS l,
                     (SELECT MAX(id) FROM c4_models) AS m,
                     (SELECT MAX(updated_at) FROM c4_models) AS n,
                     (SELECT COUNT(*) FROM checklist_runs) AS o,
                     (SELECT MAX(id) FROM checklist_runs) AS p,
                     (SELECT COUNT(*) FROM service_components) AS r_,
                     (SELECT COUNT(*) FROM components) AS s_,
                     (SELECT MAX(id) FROM components) AS t_""")
    return tuple(r.values())


def _all_chunks() -> list[dict]:
    """KB-чанки + чанки сервисов DeepArch; чанки сервисов перестраиваются при изменении БД."""
    global _DA_KEY, _DA_CHUNKS
    key = _da_key()
    with _DA_LOCK:
        if key != _DA_KEY:   # ключ фиксируется после построения — гонки не «консервируют» протухший индекс
            chunks = _deeparch_chunks()
            _DA_CHUNKS = chunks
            _DA_KEY = key
            _rebuild_idf()
    return CHUNKS + _DA_CHUNKS


def _score(query_tokens, chunk):
    vec = _vector(_tokenize(chunk["chunk"]))
    s = 0.0
    for t in query_tokens:
        if t in vec and t in _IDF:
            s += (1 + math.log(vec[t])) * _IDF[t]
    return s


def retrieve(question: str, k: int = 3):
    """Поиск по общему индексу: KB-чанки + чанки сервисов DeepArch (ассистент)."""
    q = _tokenize(question)
    chunks = _all_chunks()
    scored = sorted(((_score(q, c), i) for i, c in enumerate(chunks)), reverse=True)
    hits = [(s, i) for s, i in scored if s > 0][:k]
    return [chunks[i] for _, i in hits]


def retrieve_kb(question: str, k: int = 3):
    """KB-only поиск (страницы стандарта без чанков сервисов) — для AI-черновиков артефактов."""
    q = _tokenize(question)
    scored = sorted(((_score(q, c), i) for i, c in enumerate(CHUNKS)), reverse=True)
    hits = [(s, i) for s, i in scored if s > 0][:k]
    return [CHUNKS[i] for _, i in hits]


def _extractive(question, hits) -> str:
    """Fallback-режим: извлекающий ответ из релевантных чанков (без LLM)."""
    q = set(_tokenize(question))
    best = []
    for c in hits:
        sentences = sorted(_split_sentences(c["chunk"]),
                           key=lambda s: len(q & set(_tokenize(s))), reverse=True)
        if sentences and len(q & set(_tokenize(sentences[0]))) > 0:
            best.append((len(q & set(_tokenize(sentences[0]))), sentences[0]))
    best.sort(key=lambda x: -x[0])
    top = best[:3] if best else [(0, _split_sentences(hits[0]["chunk"])[0])]
    return "\n\n".join(f"· {s}" for _, s in top)


SYSTEM_PROMPT = """Ты — ассистент архитектора по корпоративному стандарту \
«Architecture Definition Set» компании dats.tech и платформе DeepArch. Отвечай на русском языке.

Правила:
1. Опирайся ТОЛЬКО на приведённый контекст: страницы стандарта И данные платформы
   DeepArch (реестр сервисов, карточки, артефакты, C4-модели, техдолг, ревью).
   Если ответа в контексте нет — честно скажи об этом и предложи, куда посмотреть.
2. Не выдумывай номера страниц, пунктов, правил и атрибутов сервисов.
3. Отвечай кратко и по делу: суть, затем детали. Можно использовать списки.
4. Ты работаешь в advisory-режиме: только объясняешь и анализируешь, никаких действий.
5. Данные включают личный контекст пользователя (роль, его сервисы, группы, назначенные
   ревью, техдолг на нём) — учитывай роль и зону ответственности при рекомендациях
   и различай «мои сервисы» и «остальной ландшафт»."""

TOOL_PROMPT = """

6. Если данных в контексте недостаточно для ответа о сервисах DeepArch, вызывай
   инструменты: search_services — найти сервисы по коду/имени/домену (вернёт id);
   get_architecture — подробный контекст сервиса по id (карточка, требования,
   артефакты, C4, техдолг, ревью). Не вызывай инструменты без необходимости."""

MAX_TOOL_ROUNDS = 2   # раунды вызова инструментов на один вопрос

TOOLS = [
    {"type": "function", "function": {
        "name": "search_services",
        "description": "Найти сервисы в реестре платформы DeepArch по подстроке кода, "
                       "имени или домена. Возвращает id, код, имя, домен, статус ревью, "
                       "жизненный цикл и владельца.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Подстрока кода, имени или домена"},
            "domain": {"type": "string", "description": "Фильтр по домену"},
            "limit": {"type": "integer", "description": "Максимум сервисов (1-20, по умолчанию 10)"},
        }, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "get_architecture",
        "description": "Подробный контекст сервиса DeepArch по id (id берётся из "
                       "search_services или реестра в контексте): карточка, требования, "
                       "компоненты, состояние артефактов, self-check, техдолг, ревью, "
                       "контент артефактов и C4-модели.",
        "parameters": {"type": "object", "properties": {
            "service_id": {"type": "integer", "description": "id сервиса из реестра"},
        }, "required": ["service_id"]}}},
]


def _parse_args(raw) -> dict:
    """arguments от модели: JSON-строка (или уже dict — некоторые шлюзы так отдают)."""
    if isinstance(raw, dict):
        return raw
    try:
        args = json.loads(raw or "{}")
        return args if isinstance(args, dict) else {}
    except (ValueError, TypeError):
        return {}


def _tool_search_services(args: dict) -> str:
    query = (args.get("query") or "").strip().lower()
    domain = (args.get("domain") or "").strip().lower()
    try:
        limit = max(1, min(int(args.get("limit") or 10), 20))
    except (TypeError, ValueError):
        limit = 10
    rows = q("SELECT id, code, name, domain, review_status, lifecycle, owner "
             "FROM services ORDER BY id")

    def match(r):
        if domain and domain not in (r["domain"] or "").lower():
            return False
        if not query:
            return True
        return any(query in (r[k] or "").lower() for k in ("code", "name", "domain"))

    out = [{"id": r["id"], "code": r["code"], "name": r["name"],
            "domain": r["domain"], "review_status": r["review_status"],
            "lifecycle": r["lifecycle"], "owner": r["owner"]}
           for r in rows if match(r)]
    return json.dumps({"services": out[:limit], "total_matched": len(out)},
                      ensure_ascii=False)


def _tool_get_architecture(args: dict) -> str:
    try:
        sid = int(args.get("service_id") or 0)
    except (TypeError, ValueError):
        return json.dumps({"error": "service_id должен быть числом"}, ensure_ascii=False)
    ctx = _service_context(sid, None)
    if not ctx:
        return json.dumps({"error": f"сервис id={sid} не найден"}, ensure_ascii=False)
    return ctx


def _run_tool(name: str, args_raw) -> str:
    args = _parse_args(args_raw)
    if name == "search_services":
        return _tool_search_services(args)
    if name == "get_architecture":
        return _tool_get_architecture(args)
    return json.dumps({"error": f"неизвестный инструмент: {name}"}, ensure_ascii=False)


def _tool_assistant_msg(calls: list[dict]) -> dict:
    """Сообщение assistant с tool_calls в формате OpenAI — для истории диалога."""
    return {"role": "assistant", "content": "",
            "tool_calls": [{"id": c["id"], "type": "function",
                            "function": {"name": c["name"], "arguments": c["arguments"]}}
                           for c in calls]}


def _tools_unsupported(e: llm.LLMError) -> bool:
    """Прокси/модель не приняли tools (HTTP 4xx) — стоит повторить запрос без них."""
    return getattr(e, "status_code", None) in (400, 404, 422)


def _agent_answer(msgs: list[dict], model: str) -> tuple[str, list[dict]]:
    """Агентный цикл без стриминга: вызовы инструментов → финальный текст.

    Возврат: (текст ответа, использованные инструменты [{name, arguments}]).
    Бросает LLMError (проксируется вызывающему коду).
    """
    if msgs and msgs[0]["role"] == "system":
        msgs = [{**msgs[0], "content": msgs[0]["content"] + TOOL_PROMPT}, *msgs[1:]]
    used = []
    for rnd in range(MAX_TOOL_ROUNDS + 1):
        msg = llm.chat_tools(msgs, TOOLS, model=model)
        calls = msg.get("tool_calls") or []
        if not calls or rnd == MAX_TOOL_ROUNDS:
            return (msg.get("content") or "").strip(), used
        msgs.append(_tool_assistant_msg(calls))
        for c in calls:
            used.append({"name": c["name"], "arguments": _parse_args(c["arguments"])})
            msgs.append({"role": "tool", "tool_call_id": c["id"],
                         "content": _run_tool(c["name"], c["arguments"])[:8000]})
    raise llm.LLMError("агентный цикл не завершился")   # недостижимо, защита для типов


def _agent_stream(msgs: list[dict], model: str):
    """Агентный цикл со стримингом: генератор событий {"type":"delta","text"} и
    {"type":"tool_calls","tool_calls":[{name,arguments,id}]} (после исполнения).

    Дельты контента отдаются сразу; tool_calls — после исполнения инструмента.
    """
    if msgs and msgs[0]["role"] == "system":
        msgs = [{**msgs[0], "content": msgs[0]["content"] + TOOL_PROMPT}, *msgs[1:]]
    for rnd in range(MAX_TOOL_ROUNDS + 1):
        calls = []
        for ev in llm.chat_stream_tools(msgs, TOOLS, model=model):
            if ev["type"] == "delta":
                yield ev
            else:
                calls = ev["tool_calls"]
        if not calls or rnd == MAX_TOOL_ROUNDS:
            return
        msgs.append(_tool_assistant_msg(calls))
        done = []
        for c in calls:
            result = _run_tool(c["name"], c["arguments"])[:8000]
            done.append({"id": c["id"], "name": c["name"],
                         "arguments": _parse_args(c["arguments"])})
            msgs.append({"role": "tool", "tool_call_id": c["id"], "content": result})
        yield {"type": "tool_calls", "tool_calls": done}


def _dedupe_citations(cits: list[dict]) -> list[dict]:
    out, seen = [], set()
    for c in cits:
        if c["page_id"] in seen:
            continue
        seen.add(c["page_id"])
        out.append(c)
    return out


def _prep(question: str, k: int = 4):
    """Поиск релевантных чанков + сборка контекста и цитат (общее для answer/answer_stream)."""
    hits = retrieve(question, k)
    if not hits:
        return None
    q = set(_tokenize(question))
    citations, seen, ctx = [], set(), []
    for n, c in enumerate(hits, 1):
        if c["page_id"] not in seen:
            seen.add(c["page_id"])
            citations.append({"page_id": c["page_id"], "title": c["title"], "url": c["url"]})
        best_sent = max(_split_sentences(c["chunk"]),
                        key=lambda s: len(q & set(_tokenize(s))), default="")
        ctx.append(f"[{n}] {c['title']} (pageId={c['page_id']}):\n{c['chunk']}"
                   + (f"\nРелевантный фрагмент: {best_sent}" if best_sent else ""))
    return citations, ctx, q, hits


def _registry_lines() -> str:
    """Слой 1: компактный реестр ИС DeepArch — разрешение имён и вопросы уровня реестра.

    Лимит 60 строк: реестр целиком кладётся в каждый LLM-промпт, при росте
    ландшафта он не должен вытеснять KB-чанки (упомянутый вне лимита сервис
    всё равно разрешится через _find_service).
    """
    rows = q("SELECT id, code, name, domain, review_status, lifecycle, owner "
             "FROM services ORDER BY id")
    if not rows:
        return ""
    lines = ["Реестр сервисов платформы DeepArch (id · код · имя · домен · ревью · ЖЦ · владелец):"]
    lines += [f"- id={r['id']} · {r['code']} · {r['name']} · {r['domain'] or '—'} · "
              f"ревью: {r['review_status']} · ЖЦ: {r['lifecycle']} · владелец: {r['owner'] or '—'}"
              for r in rows[:60]]
    if len(rows) > 60:
        lines.append(f"- … и ещё {len(rows) - 60} сервисов (назовите код или имя — расскажу подробнее)")
    return "\n".join(lines)


def _personal_context(user) -> str | None:
    """Слой 4: персональный контекст пользователя — роль, мои сервисы, группы,
    назначенные ревью, техдолг на пользователе. None — данных нет."""
    if not user:
        return None
    uname = user.get("username") or ""
    lines = [(f"Пользователь: {user.get('display_name') or uname} (@{uname}), "
              f"роль: {user.get('role') or '—'}.")]
    ids = roles.my_service_ids(user)[:200]   # потолок переменных SQLite для IN (…)
    if ids:
        ph = ",".join("?" * len(ids))
        rows = q(f"SELECT id, code, name, lifecycle, review_status FROM services "
                 f"WHERE id IN ({ph}) ORDER BY id", ids)
        lines.append("Мои сервисы (владелец/архитектор или моя product-группа):")
        lines += [f"- id={r['id']} · {r['code']} · {r['name']} · "
                  f"ЖЦ: {r['lifecycle']} · ревью: {r['review_status']}" for r in rows[:20]]
        if len(rows) > 20:
            lines.append(f"- … и ещё {len(rows) - 20}")
    groups = roles.user_groups(uname)
    if groups:
        lines.append("Мои группы доступа: " + "; ".join(
            f"{g['name']} ({g['kind']})" for g in groups) + ".")
    if roles.has_global(user, "review.decide") or roles.in_committee(uname):
        revs = q("""SELECT r.id, s.code, s.name, s.id AS sid FROM reviews r
                    JOIN services s ON s.id = r.service_id
                    WHERE r.status='in_review' ORDER BY r.id DESC LIMIT 10""")
        if revs:
            lines.append("Ревью, ожидающие моего решения:")
            lines += [f"- {r['code']} · {r['name']} (id={r['sid']})" for r in revs]
    debts = q("""SELECT t.debt_id, t.title, t.priority, s.code FROM tech_debts t
                 JOIN services s ON s.id=t.service_id
                 WHERE t.owner=? AND t.status NOT IN ('closed','paid')
                 ORDER BY t.id DESC LIMIT 10""", (uname,))
    if debts:
        lines.append("Техдолг, за который отвечаю:")
        lines += [f"- {d['debt_id']} {d['title'][:60]} ({d['code']}, приоритет {d['priority']})"
                  for d in debts]
    return "\n".join(lines) if len(lines) > 1 else None


def _split_long(para: str) -> list[str]:
    """Одиночный абзац длиннее лимита режется по границам слов."""
    parts = []
    while len(para) > _CHUNK:
        cut = para.rfind(" ", 0, _CHUNK)
        cut = _CHUNK if cut < 100 else cut
        parts.append(para[:cut].strip())
        para = para[cut:].strip()
    if para:
        parts.append(para)
    return parts


def _pack(text: str) -> list[str]:
    """Резка текста на чанки до _CHUNK символов по абзацам (как _chunks, для одного текста)."""
    out, cur = [], ""
    for para in (t.strip() for t in text.split("\n\n") if t.strip()):
        for piece in _split_long(para):
            if cur and len(cur) + len(piece) > _CHUNK:
                out.append(cur)
                cur = ""
            cur = (cur + "\n\n" + piece).strip()
    if cur:
        out.append(cur)
    return out


def _deeparch_chunks() -> list[dict]:
    """Вариант B: сервисы DeepArch в общем RAG-индексе — карточка + архитектура.

    По чанку на сервис (данные карточки, требования, компоненты, техдолг, self-check)
    плюс чанк архитектуры (контент артефактов + C4), если она заполнена. Цитаты ведут
    в карточку сервиса; page_id уникален по сервису — дедупликация цитат в _prep.
    """
    out = []
    for svc in q("SELECT * FROM services ORDER BY id"):
        base = {"page_id": f"deeparch-{svc['id']}",
                "title": f"DeepArch · {svc['name']} ({svc['code']})",
                "url": f"#/service/{svc['id']}/card"}
        lines = [(f"Сервис {svc['name']} ({svc['code']}), домен: {svc['domain'] or '—'}, "
                  f"тип проекта: {svc['project_type']}, ЖЦ: {svc['lifecycle']}, "
                  f"ревью: {svc['review_status']}, владелец: {svc['owner'] or '—'}, "
                  f"архитектор: {svc['architect'] or '—'}.")]
        reqs = q("SELECT req_type, ext_id, text FROM requirements WHERE service_id=? "
                 "ORDER BY req_type, id LIMIT 15", (svc["id"],))
        if reqs:
            lines.append("Требования: " + "; ".join(
                f"{r['ext_id']} {r['text'][:120]}" for r in reqs) + ".")
        comps = q("SELECT c.name, c.kind, c.status FROM components c "
                  "JOIN service_components sc ON sc.component_id=c.id "
                  "WHERE sc.service_id=? LIMIT 15", (svc["id"],))
        if comps:
            lines.append("Компоненты: " + "; ".join(
                f"{c['name']} ({c['kind']}, {c['status']})" for c in comps) + ".")
        run = q1("SELECT score_pct, mandatory_missing FROM checklist_runs WHERE service_id=? "
                 "ORDER BY created_at DESC LIMIT 1", (svc["id"],))
        if run:
            lines.append(f"Последний self-check: {run['score_pct']}%, "
                         f"обязательных не закрыто: {run['mandatory_missing']}.")
        debts = q("SELECT debt_id, title, priority, status, risk FROM tech_debts "
                  "WHERE service_id=? ORDER BY id LIMIT 10", (svc["id"],))
        if debts:
            lines.append("Техдолг: " + "; ".join(
                f"{d['debt_id']} {d['title'][:60]} ({d['priority']}, {d['status']}, "
                f"риск {d['risk']})" for d in debts) + ".")
        for part in _pack("\n\n".join(lines)):
            out.append({**base, "chunk": part})
        arch = _artifact_content(svc["id"], None, limit=2, chars=600) + _c4_lines(svc["id"])
        if arch:
            arch_text = "Архитектура и проектные материалы:\n" + "\n\n".join(
                "- " + a for a in arch)
            for part in _pack(arch_text):
                out.append({**base, "chunk": part})
    return out


def _find_service(question: str):
    """Разрешение упоминания сервиса в вопросе: сначала код (границы слова), затем имя."""
    ql = question.lower()
    for r in q("SELECT id, code, name FROM services ORDER BY id"):
        c = (r["code"] or "").strip().lower()
        if len(c) >= 2 and re.search(rf"(?<![\wа-яё]){re.escape(c)}(?![\wа-яё])", ql):
            return r
    for r in q("SELECT id, code, name FROM services ORDER BY id"):
        n = (r["name"] or "").strip().lower()
        if len(n) >= 4 and n in ql:
            return r
    return None


def _c4_lines(service_id: int, max_lines: int = 18) -> list[str]:
    """C4-модели сервиса текстом: узлы (имя, тип, технология) и связи."""
    out = []
    for r in q("SELECT view, model_json FROM c4_models WHERE service_id=?", (service_id,)):
        try:
            m = json.loads(r["model_json"] or "{}")
        except (ValueError, TypeError):
            continue
        nodes = m.get("nodes") or []
        edges = m.get("edges") or []
        if not nodes:
            continue
        by_id = {n.get("id"): n for n in nodes}
        out.append(f"C4-модель, вид «{r['view']}» — узлы: " + "; ".join(
            f"{n.get('name') or '?'} ({n.get('type') or '?'}"
            + (f", {n['tech']}" if (n.get("tech") or "").strip() else "") + ")"
            for n in nodes[:12]))
        for e in edges[:10]:
            a, b = by_id.get(e.get("from")), by_id.get(e.get("to"))
            if a and b:
                meta = [m for m in (e.get("label") or "", e.get("tech") or "") if m.strip()]
                out.append(f"  связь: {a.get('name') or '?'} → {b.get('name') or '?'}"
                           + (f" ({', '.join(meta)})" if meta else ""))
        if len(out) >= max_lines:
            break
    return out


def _artifact_content(service_id: int, question: str | None,
                      limit: int = 3, chars: int = 900) -> list[str]:
    """Контент артефактов сервиса: релевантные вопросу первыми, с диаграммами."""
    arts = q("SELECT kind, content_md, diagram_code FROM artifacts WHERE service_id=? "
             "ORDER BY kind", (service_id,))
    filled = [a for a in arts if (a["content_md"] or "").strip() or (a["diagram_code"] or "").strip()]
    if not filled:
        return []
    qt = set(_tokenize(question or ""))
    title = {a["kind"]: a["title"] for a in ARTIFACT_KINDS}

    def score(a):
        toks = set(_tokenize(a["kind"])) | set(_tokenize((a["content_md"] or "")[:400]))
        return len(qt & toks)

    filled.sort(key=score, reverse=True)
    out = []
    for a in filled[:limit]:
        body = (a["content_md"] or "").strip()[:chars]
        diag = (a["diagram_code"] or "").strip()[:500]
        out.append(f"Артефакт «{title.get(a['kind'], a['kind'])}»:\n{body}"
                   + (f"\nДиаграмма (Mermaid):\n{diag}" if diag else ""))
    return out


def _service_context(service_id: int, question: str | None = None) -> str | None:
    """Факты о сервисе из DeepArch — чтобы ассистент отвечал в контексте конкретного сервиса."""
    svc = q1("SELECT * FROM services WHERE id=?", (service_id,))
    if not svc:
        return None
    title = {a["kind"]: a["title"] for a in ARTIFACT_KINDS}
    comps = q("SELECT c.name, c.kind, c.status FROM components c "
              "JOIN service_components sc ON sc.component_id=c.id "
              "WHERE sc.service_id=? LIMIT 15", (service_id,))
    arts = q("SELECT kind, content_md, diagram_code, source_url FROM artifacts "
             "WHERE service_id=? ORDER BY kind", (service_id,))
    lines = [(f"Сервис в системе DeepArch: {svc['name']} ({svc['code']}), "
              f"домен: {svc['domain'] or '—'}, тип проекта: {svc['project_type']}, "
              f"жизненный цикл: {svc['lifecycle']}, владелец: {svc['owner'] or '—'}, "
              f"архитектор: {svc['architect'] or '—'}.")]
    reqs = q("SELECT req_type, ext_id, text FROM requirements WHERE service_id=? "
             "ORDER BY req_type, id LIMIT 15", (service_id,))
    if reqs:
        lines.append("Требования сервиса (ФТ — функции, НФТ — измеримые качества):")
        lines += [f"- {r['ext_id']}: {r['text'][:160]}" for r in reqs]
    if comps:
        lines.append("Компоненты: " + "; ".join(
            f"{c['name']} ({c['kind']}, {c['status']})" for c in comps) + ".")
    if arts:
        states = []
        for a in arts:
            st = "заполнен" if (a["content_md"] or "").strip() else "пуст"
            if (a["diagram_code"] or "").strip():
                st += ", есть диаграмма"
            states.append(f"{title.get(a['kind'], a['kind'])} — {st}")
        lines.append("Состояние артефактов: " + "; ".join(states) + ".")
    run = q1("SELECT score_pct, mandatory_missing FROM checklist_runs WHERE service_id=? "
             "ORDER BY created_at DESC LIMIT 1", (service_id,))
    if run:
        lines.append(f"Последний self-check: {run['score_pct']}%, "
                     f"обязательных не закрыто: {run['mandatory_missing']}.")
    debts = q("SELECT debt_id, dtype, title, priority, status, risk FROM tech_debts "
              "WHERE service_id=? ORDER BY id LIMIT 10", (service_id,))
    if debts:
        lines.append("Техдолг сервиса: " + "; ".join(
            f"{d['debt_id']} {d['title'][:60]} ({d['dtype']}, {d['priority']}, "
            f"{d['status']}, риск {d['risk']})" for d in debts) + ".")
    rev = q1("SELECT status, requested_by, reviewer, comment FROM reviews "
             "WHERE service_id=? ORDER BY id DESC LIMIT 1", (service_id,))
    if rev:
        lines.append(f"Последнее ревью: {rev['status']} (запросил {rev['requested_by'] or '—'}"
                     + (f", решение {rev['reviewer']}" if rev["reviewer"] else "") + ").")
    # архитектура: контент релевантных артефактов + C4-модели (то, что спрашивают как «архитектуру»)
    arch = _artifact_content(service_id, question) + _c4_lines(service_id)
    if arch:
        lines.append("Архитектура и проектные материалы:")
        lines += ["- " + a for a in arch]
    return "\n".join(lines)


def _llm_messages(question: str, ctx: list, history: list | None,
                  service_ctx: str | None = None, registry: str | None = None,
                  personal: str | None = None) -> list[dict]:
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    # последний диалог (максимум 6 реплик) — для follow-up вопросов
    for m in (history or [])[-6:]:
        role, content = m.get("role"), (m.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            msgs.append({"role": role, "content": content[:2000]})
    parts = []
    if personal:
        parts.append("Персональный контекст пользователя:\n" + personal)
    if registry:
        parts.append("Данные платформы DeepArch (реестр сервисов):\n" + registry)
    if ctx:
        parts.append("Контекст из базы знаний стандарта:\n\n" + "\n\n".join(ctx))
    if service_ctx:
        parts.append("Контекст конкретного сервиса в DeepArch:\n" + service_ctx)
    if not parts:
        parts.append("Релевантных данных по вопросу не найдено.")
    parts.append(f"Вопрос архитектора: {question}\n"
                 "Ответь на вопрос строго по приведённым данным.")
    msgs.append({"role": "user", "content": "\n\n".join(parts)})
    return msgs


def _resolve_service(question: str, service_id: int | None):
    """Приоритет источника контекста: явный чип из карточки > упоминание в вопросе."""
    if service_id:
        r = q1("SELECT id, code, name FROM services WHERE id=?", (service_id,))
        if r:
            return r
    return _find_service(question) if question else None


def _deeparch_citation(svc) -> dict:
    return {"page_id": f"deeparch-{svc['id']}", "title": f"DeepArch · {svc['name']} ({svc['code']})",
            "url": f"#/service/{svc['id']}/card"}


def answer(question: str, k: int = 4, history: list | None = None, model: str = "",
           service_id: int | None = None, user: dict | None = None) -> dict:
    """Ответ ассистента: LLM по контексту (стандарт + данные DeepArch) или fallback + цитаты.

    history — предыдущий диалог [{role: user|assistant, content: str}]
    для follow-up вопросов (используется только LLM-веткой).
    model — переопределение модели LLM (выбор в чате).
    service_id — контекст сервиса из DeepArch (ассистент в карточке сервиса);
    если не задан — сервис разрешается по упоминанию имени/кода в вопросе.
    user — авторизованный пользователь: включает Слой 4 (персональный контекст).
    """
    svc = _resolve_service(question, service_id)
    svc_ctx = _service_context(svc["id"], question) if svc else None
    registry = _registry_lines() if llm.configured() else None   # в fallback реестр не нужен
    personal = _personal_context(user)
    prep = _prep(question, k)
    if prep is None and not svc_ctx and not personal:
        return {"answer": "Ни в базе знаний стандарта, ни в данных DeepArch нет "
                          "релевантного. Уточните вопрос или откройте стандарт напрямую.",
                "citations": [], "confidence": 0.0, "provider": "none"}
    citations = _dedupe_citations(([_deeparch_citation(svc)] if svc else [])
                                  + (prep[0] if prep else []))
    ctx = prep[1] if prep else []
    q = prep[2] if prep else set()
    hits = prep[3] if prep else []
    if llm.configured():
        msgs = _llm_messages(question, ctx, history, svc_ctx, registry, personal)
        tools_used: list[dict] = []
        try:
            try:
                text, tools_used = _agent_answer(msgs, model)
            except llm.LLMError as e:
                if not _tools_unsupported(e):
                    raise
                text = llm.chat(msgs, model=model)   # прокси/модель без tools — повтор без них
            if not text.strip():
                raise llm.LLMError("LLM вернула пустой ответ")
            out = {"answer": text.strip(), "citations": citations,
                   "confidence": 0.9, "provider": "ai-buddy",
                   "model": (model or "").strip() or llm.config()[2]}
            if tools_used:
                out["tools"] = tools_used
            return out
        except llm.LLMError as e:
            note = f"\n\n⚠ LLM недоступна ({e}) — извлекающий ответ:"
        else:
            note = ""
    else:
        note = ("\n\n⚠ AI-Buddy не подключён (задайте AI_BUDDY_URL / AI_BUDDY_TOKEN) — "
                "пока извлекающий ответ:")
    if hits:
        text = _extractive(question, hits)
        confidence = round(min(1.0, len(q & set(_tokenize(text))) / max(3, len(q))), 2) if q else 0.0
    else:
        # релевантных страниц стандарта нет — отдаём данные DeepArch как есть
        text = "По данным платформы DeepArch:\n" + (svc_ctx or personal or "")
        confidence = 0.6
    return {"answer": note + "\n\n" + text if note else text,
            "citations": citations, "confidence": confidence, "provider": "local-rag"}


def answer_stream(question: str, k: int = 4, history: list | None = None, model: str = "",
                  service_id: int | None = None, user: dict | None = None):
    """Стриминговая версия answer(): генератор событий для SSE.

    События: {"type":"meta", provider, model, confidence, citations}
             {"type":"delta", text}          — дельта ответа
             {"type":"done"}
    model — переопределение модели LLM (выбор в чате).
    service_id — контекст сервиса из DeepArch (ассистент в карточке сервиса);
    если не задан — сервис разрешается по упоминанию имени/кода в вопросе.
    user — авторизованный пользователь: включает Слой 4 (персональный контекст).
    Fallback при ошибке LLM / без конфигурации: извлекающий ответ одной дельтой.
    """
    svc = _resolve_service(question, service_id)
    svc_ctx = _service_context(svc["id"], question) if svc else None
    registry = _registry_lines() if llm.configured() else None   # в fallback реестр не нужен
    personal = _personal_context(user)
    prep = _prep(question, k)
    if prep is None and not svc_ctx and not personal:
        yield {"type": "meta", "provider": "none", "model": None,
               "confidence": 0.0, "citations": []}
        yield {"type": "delta", "text": "Ни в базе знаний стандарта, ни в данных DeepArch нет "
                                        "релевантного. Уточните вопрос или откройте стандарт напрямую."}
        yield {"type": "done"}
        return
    citations = _dedupe_citations(([_deeparch_citation(svc)] if svc else [])
                                  + (prep[0] if prep else []))
    ctx = prep[1] if prep else []
    q = prep[2] if prep else set()
    hits = prep[3] if prep else []
    if llm.configured():
        _url, _tok, def_model = llm.config()
        eff_model = (model or "").strip() or def_model
        yield {"type": "meta", "provider": "ai-buddy", "model": eff_model,
               "confidence": 0.9, "citations": citations}
        full = []
        tools_used = []
        msgs = _llm_messages(question, ctx, history, svc_ctx, registry, personal)
        try:
            try:
                for ev in _agent_stream(msgs, eff_model):
                    if ev["type"] == "delta":
                        full.append(ev["text"])
                        yield {"type": "delta", "text": ev["text"]}
                    else:   # tool_calls — инструменты уже исполнены
                        tools_used += ev["tool_calls"]
                        yield {"type": "tool_use", "tools": ev["tool_calls"]}
            except llm.LLMError as e:
                if not _tools_unsupported(e) or full:
                    raise
                for delta in llm.chat_stream(msgs, model=eff_model):
                    full.append(delta)   # прокси/модель без tools — повтор без них
                    yield {"type": "delta", "text": delta}
            if full:
                yield {"type": "done"}
                return
            yield {"type": "delta", "text": "\n\n⚠ LLM вернула пустой ответ — "
                                            "извлекающий ответ:"}
        except llm.LLMError as e:
            yield {"type": "delta",
                   "text": (f"\n\n⚠ LLM недоступна ({e}) — извлекающий ответ:")
                   if full else f"⚠ LLM недоступна ({e}) — извлекающий ответ:"}
    else:
        yield {"type": "meta", "provider": "local-rag", "model": None,
               "confidence": None, "citations": citations}
        yield {"type": "delta",
               "text": "⚠ AI-Buddy не подключён (подключите в админ-панели → Интеграции) — "
                       "пока извлекающий ответ:\n\n"}
    if hits:
        text = _extractive(question, hits)
        confidence = round(min(1.0, len(q & set(_tokenize(text))) / max(3, len(q))), 2) if q else 0.0
    else:
        text = "По данным платформы DeepArch:\n" + (svc_ctx or personal or "")
        confidence = 0.6
    yield {"type": "delta", "text": text}
    yield {"type": "meta", "provider": "local-rag", "model": None,
           "confidence": confidence, "citations": citations}
    yield {"type": "done"}


def status() -> dict:
    url, _, model = llm.config()
    return {"provider": "ai-buddy" if llm.configured() else "local-rag",
            "model": model if llm.configured() else None,
            "source": llm.source(),
            "kb_pages": len(PAGES), "kb_chunks": len(CHUNKS),
            "deeparch_chunks": len(_all_chunks()) - len(CHUNKS),
            "ai_buddy_url": url or None}
