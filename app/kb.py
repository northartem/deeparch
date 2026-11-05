"""RAG-ассистент (MVP2 BR-48…50): LLM-генерация поверх базы знаний стандарта.

Контекст — реальные страницы Confluence dats.tech (kb_data.py). Ответ генерирует
корпоративная LLM (AI-Buddy, app/llm.py) строго по извлечённому контексту;
если LLM не сконфигурирована/недоступна — извлекающий ответ из тех же чанков.
В обоих режимах возвращаются цитаты (pageId, title, url) и режим advisory:
ассистент только отвечает, ничего не меняет (BR-33).
"""
import math
import os
import re
from . import llm
from .kb_data import PAGES

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
«Architecture Definition Set» компании dats.tech. Отвечай на русском языке.

Правила:
1. Опирайся ТОЛЬКО на приведённый контекст из стандарта. Если ответа в контексте нет —
   честно скажи об этом и предложи, куда посмотреть.
2. Не выдумывай номера страниц, пунктов и правил.
3. Отвечай кратко и по делу: суть, затем детали. Можно использовать списки.
4. Ты работаешь в advisory-режиме: только объясняешь стандарт, никаких действий."""


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


def _llm_messages(question: str, ctx: list, history: list | None) -> list[dict]:
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    # последний диалог (максимум 6 реплик) — для follow-up вопросов
    for m in (history or [])[-6:]:
        role, content = m.get("role"), (m.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            msgs.append({"role": role, "content": content[:2000]})
    msgs.append({"role": "user", "content":
            "Контекст из базы знаний стандарта:\n\n" + "\n\n".join(ctx)
            + f"\n\nВопрос архитектора: {question}\n"
              "Ответь на вопрос строго по контексту."})
    return msgs


def answer(question: str, k: int = 4, history: list | None = None, model: str = "") -> dict:
    """Ответ ассистента: LLM по контексту из базы знаний (или fallback) + цитаты.

    history — предыдущий диалог [{role: user|assistant, content: str}]
    для follow-up вопросов (используется только LLM-веткой).
    model — переопределение модели LLM (выбор в чате).
    """
    prep = _prep(question, k)
    if prep is None:
        return {"answer": "В базе знаний стандарта нет релевантного раздела. "
                          "Уточните вопрос или откройте стандарт напрямую.",
                "citations": [], "confidence": 0.0, "provider": "none"}
    citations, ctx, q, hits = prep
    if llm.configured():
        try:
            text = llm.chat(_llm_messages(question, ctx, history), model=model)
            return {"answer": text.strip(), "citations": citations,
                    "confidence": 0.9, "provider": "ai-buddy",
                    "model": (model or "").strip() or llm.config()[2]}
        except llm.LLMError as e:
            note = f"\n\n⚠ LLM недоступна ({e}) — извлекающий ответ из базы знаний:"
        else:
            note = ""
    else:
        note = ("\n\n⚠ AI-Buddy не подключён (задайте AI_BUDDY_URL / AI_BUDDY_TOKEN) — "
                "пока извлекающий ответ из базы знаний:")
    text = _extractive(question, hits)
    confidence = round(min(1.0, len(q & set(_tokenize(text))) / max(3, len(q))), 2) if q else 0.0
    return {"answer": note + "\n\n" + text if note else text,
            "citations": citations, "confidence": confidence, "provider": "local-rag"}


def answer_stream(question: str, k: int = 4, history: list | None = None, model: str = ""):
    """Стриминговая версия answer(): генератор событий для SSE.

    События: {"type":"meta", provider, model, confidence, citations}
             {"type":"delta", text}          — дельта ответа
             {"type":"done"}
    model — переопределение модели LLM (выбор в чате).
    Fallback при ошибке LLM / без конфигурации: извлекающий ответ одной дельтой.
    """
    prep = _prep(question, k)
    if prep is None:
        yield {"type": "meta", "provider": "none", "model": None,
               "confidence": 0.0, "citations": []}
        yield {"type": "delta", "text": "В базе знаний стандарта нет релевантного раздела. "
                                        "Уточните вопрос или откройте стандарт напрямую."}
        yield {"type": "done"}
        return
    citations, ctx, q, hits = prep
    if llm.configured():
        url_, _tok, def_model = llm.config()
        eff_model = (model or "").strip() or def_model
        yield {"type": "meta", "provider": "ai-buddy", "model": eff_model,
               "confidence": 0.9, "citations": citations}
        full = []
        try:
            for delta in llm.chat_stream(_llm_messages(question, ctx, history),
                                         model=eff_model):
                full.append(delta)
                yield {"type": "delta", "text": delta}
            if full:
                yield {"type": "done"}
                return
            yield {"type": "delta", "text": "\n\n⚠ LLM вернула пустой ответ — "
                                            "извлекающий ответ из базы знаний:"}
        except llm.LLMError as e:
            yield {"type": "delta",
                   "text": (f"\n\n⚠ LLM недоступна ({e}) — извлекающий ответ из базы знаний:")
                   if full else f"⚠ LLM недоступна ({e}) — извлекающий ответ из базы знаний:"}
    else:
        yield {"type": "meta", "provider": "local-rag", "model": None,
               "confidence": None, "citations": citations}
        yield {"type": "delta",
               "text": "⚠ AI-Buddy не подключён (подключите в админ-панели → Интеграции) — "
                       "пока извлекающий ответ из базы знаний:\n\n"}
    text = _extractive(question, hits)
    confidence = round(min(1.0, len(q & set(_tokenize(text))) / max(3, len(q))), 2) if q else 0.0
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
