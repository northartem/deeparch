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

from . import llm
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


def _tokenize(text):
    return [t for t in re.findall(r"\w{3,}", text.lower())]


def _vector(tokens):
    tf = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    return tf


def _build():
    global _IDF
    df = {}
    for c in CHUNKS:
        for t in set(_tokenize(c["chunk"])):
            df[t] = df.get(t, 0) + 1
    n = len(CHUNKS)
    _IDF = {t: math.log(n / (1 + k)) + 1.0 for t, k in df.items()}


_build()


def _score(query_tokens, chunk):
    vec = _vector(_tokenize(chunk["chunk"]))
    s = 0.0
    for t in query_tokens:
        if t in vec and t in _IDF:
            s += (1 + math.log(vec[t])) * _IDF[t]
    return s


def retrieve(question: str, k: int = 3):
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
4. Ты работаешь в advisory-режиме: только объясняешь и анализируешь, никаких действий."""


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
                  service_ctx: str | None = None, registry: str | None = None) -> list[dict]:
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    # последний диалог (максимум 6 реплик) — для follow-up вопросов
    for m in (history or [])[-6:]:
        role, content = m.get("role"), (m.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            msgs.append({"role": role, "content": content[:2000]})
    parts = []
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
    return {"page_id": "deeparch", "title": f"DeepArch · {svc['name']} ({svc['code']})",
            "url": f"#/service/{svc['id']}/card"}


def answer(question: str, k: int = 4, history: list | None = None, model: str = "",
           service_id: int | None = None) -> dict:
    """Ответ ассистента: LLM по контексту (стандарт + данные DeepArch) или fallback + цитаты.

    history — предыдущий диалог [{role: user|assistant, content: str}]
    для follow-up вопросов (используется только LLM-веткой).
    model — переопределение модели LLM (выбор в чате).
    service_id — контекст сервиса из DeepArch (ассистент в карточке сервиса);
    если не задан — сервис разрешается по упоминанию имени/кода в вопросе.
    """
    svc = _resolve_service(question, service_id)
    svc_ctx = _service_context(svc["id"], question) if svc else None
    registry = _registry_lines() if llm.configured() else None   # в fallback реестр не нужен
    prep = _prep(question, k)
    if prep is None and not svc_ctx:
        return {"answer": "Ни в базе знаний стандарта, ни в данных DeepArch нет "
                          "релевантного. Уточните вопрос или откройте стандарт напрямую.",
                "citations": [], "confidence": 0.0, "provider": "none"}
    citations = ([_deeparch_citation(svc)] if svc else []) + (prep[0] if prep else [])
    ctx = prep[1] if prep else []
    q = prep[2] if prep else set()
    hits = prep[3] if prep else []
    if llm.configured():
        try:
            text = llm.chat(_llm_messages(question, ctx, history, svc_ctx, registry), model=model)
            if not text.strip():
                raise llm.LLMError("LLM вернула пустой ответ")
            return {"answer": text.strip(), "citations": citations,
                    "confidence": 0.9, "provider": "ai-buddy",
                    "model": (model or "").strip() or llm.config()[2]}
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
        # релевантных страниц стандарта нет, но есть данные DeepArch — отдаём их как есть
        text = "По данным платформы DeepArch:\n" + (svc_ctx or "")
        confidence = 0.6
    return {"answer": note + "\n\n" + text if note else text,
            "citations": citations, "confidence": confidence, "provider": "local-rag"}


def answer_stream(question: str, k: int = 4, history: list | None = None, model: str = "",
                  service_id: int | None = None):
    """Стриминговая версия answer(): генератор событий для SSE.

    События: {"type":"meta", provider, model, confidence, citations}
             {"type":"delta", text}          — дельта ответа
             {"type":"done"}
    model — переопределение модели LLM (выбор в чате).
    service_id — контекст сервиса из DeepArch (ассистент в карточке сервиса);
    если не задан — сервис разрешается по упоминанию имени/кода в вопросе.
    Fallback при ошибке LLM / без конфигурации: извлекающий ответ одной дельтой.
    """
    svc = _resolve_service(question, service_id)
    svc_ctx = _service_context(svc["id"], question) if svc else None
    registry = _registry_lines() if llm.configured() else None   # в fallback реестр не нужен
    prep = _prep(question, k)
    if prep is None and not svc_ctx:
        yield {"type": "meta", "provider": "none", "model": None,
               "confidence": 0.0, "citations": []}
        yield {"type": "delta", "text": "Ни в базе знаний стандарта, ни в данных DeepArch нет "
                                        "релевантного. Уточните вопрос или откройте стандарт напрямую."}
        yield {"type": "done"}
        return
    citations = ([_deeparch_citation(svc)] if svc else []) + (prep[0] if prep else [])
    ctx = prep[1] if prep else []
    q = prep[2] if prep else set()
    hits = prep[3] if prep else []
    if llm.configured():
        _url, _tok, def_model = llm.config()
        eff_model = (model or "").strip() or def_model
        yield {"type": "meta", "provider": "ai-buddy", "model": eff_model,
               "confidence": 0.9, "citations": citations}
        full = []
        try:
            for delta in llm.chat_stream(_llm_messages(question, ctx, history, svc_ctx, registry),
                                         model=eff_model):
                full.append(delta)
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
        text = "По данным платформы DeepArch:\n" + (svc_ctx or "")
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
            "ai_buddy_url": url or None}
