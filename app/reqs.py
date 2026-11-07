"""Требования (ФТ/НФТ): вход в архитектурную работу.

Архитектор вставляет документ с бизнес-требованиями (ФТ) и нефункциональными
требованиями (НФТ) — LLM разбирает его на отдельные требования (BR-28, advisory);
требования попадают в промпты AI-черновиков артефактов, НФТ — в NFR profile.
Покрытие (coverage) детерминировано: поиск номера требования в артефактах.
"""
import json
import re

from . import llm
from .db import exec, now, q, q1

TYPES = {"func": "ФТ", "nonfunc": "НФТ"}
_STATUSES = ("new", "in_work", "covered")

PARSE_SYSTEM = """Ты помогаешь архитектору разобрать документ с требованиями.
Разбей текст на отдельные атомарные требования и верни СТРОГО JSON-массив объектов:
[{"type": "ФТ" | "НФТ", "text": "формулировка требования"}]
Правила:
1. ФТ — что система должна делать (функции, интеграции, сценарии). НФТ — измеримые
   качества (производительность, доступность, безопасность, масштабирование, RTO/RPO).
2. Сохраняй формулировки максимально близко к оригиналу, не придумывай новых требований.
3. Номера требований не добавляй — они присваиваются системой.
4. Только JSON, без пояснений."""

DRAFT_SYSTEM = """Ты архитектурный ассистент компании ДАТС. Составь запрошенный
markdown-документ строго по предоставленным данным, по-русски, без вступлений и
прощаний. Недостающие данные помечай [TODO]. Это черновик: автор обязан проверить
и подтвердить его (advisory, BR-33)."""


def list_for(service_id: int) -> list[dict]:
    return q("SELECT * FROM requirements WHERE service_id=? ORDER BY "
             "CASE req_type WHEN 'nonfunc' THEN 0 ELSE 1 END, id", (service_id,))


def parse_document(text: str, model: str = "") -> dict:
    """AI-разбор вставленного документа на требования (LLM, fallback — построчный)."""
    text = (text or "").strip()
    if not text:
        return {"items": [], "provider": "none"}
    if llm.configured():
        try:
            raw = llm.chat([{"role": "system", "content": PARSE_SYSTEM},
                            {"role": "user", "content": text[:12000]}],
                           temperature=0.1, max_tokens=4000, model=model)
            m = re.search(r"\[.*\]", raw, re.DOTALL)
            if m:
                items = []
                for it in json.loads(m.group(0)):
                    t = (it.get("text") or "").strip()
                    typ = "nonfunc" if it.get("type", "").upper().startswith("Н") else "func"
                    if t:
                        items.append({"req_type": typ, "text": t})
                if items:
                    return {"items": items, "provider": "ai-buddy"}
        except (llm.LLMError, ValueError, KeyError):
            pass
    return {"items": _naive_parse(text), "provider": "fallback"}


def _naive_parse(text: str) -> list[dict]:
    """Fallback без LLM: каждая значимая строка — требование, тип по маркерам."""
    items = []
    for line in text.splitlines():
        line = line.strip().lstrip("-•*0123456789. ")
        if len(line) < 8:
            continue
        low = line.lower()
        typ = "nonfunc" if re.search(r"\bнфт|nfr|rps|sla|p9[59]|латент|доступност|"
                                     r"масштаб|latency|throughput|rto|rpo", low) else "func"
        items.append({"req_type": typ, "text": line})
    return items


def import_items(service_id: int, items: list[dict], source_url: str = "") -> list[dict]:
    """Сохраняет разобранные требования, присваивая номера ФТ-N / НФТ-N."""
    cnt = {"func": 0, "nonfunc": 0}
    for r in q("SELECT req_type, ext_id FROM requirements WHERE service_id=?", (service_id,)):
        m = re.match(r"^(ФТ|НФТ)-(\d+)$", r["ext_id"] or "")
        if m:
            key = "nonfunc" if m.group(1) == "НФТ" else "func"
            cnt[key] = max(cnt[key], int(m.group(2)))
    created = []
    for it in items:
        typ = it.get("req_type") if it.get("req_type") in ("func", "nonfunc") else "func"
        body = (it.get("text") or "").strip()
        if not body:
            continue
        cnt[typ] += 1
        ext_id = it.get("ext_id") or f"{TYPES[typ]}-{cnt[typ]}"
        rid = exec("INSERT INTO requirements(service_id,req_type,ext_id,text,source_url,"
                   "status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                   (service_id, typ, ext_id, body, source_url or it.get("source_url") or "",
                    "new", now(), now()))
        created.append(q1("SELECT * FROM requirements WHERE id=?", (rid,)))
    return created


def coverage(service_id: int) -> dict[int, list[str]]:
    """Какими артефактами покрыто каждое требование: номер ищется в тексте артефакта."""
    arts = q("SELECT kind, content_md, diagram_code FROM artifacts WHERE service_id=?",
             (service_id,))
    out = {}
    for r in q("SELECT id, ext_id FROM requirements WHERE service_id=?", (service_id,)):
        ext = (r["ext_id"] or "").strip()
        if not ext:
            out[r["id"]] = []
            continue
        pat = re.compile(r"(?<![A-Za-zА-Яа-я0-9-])" + re.escape(ext) + r"(?![0-9])")
        kinds = [a["kind"] for a in arts
                 if pat.search(a["content_md"] or "") or pat.search(a["diagram_code"] or "")]
        out[r["id"]] = kinds
    return out


def nonfunc_items(service_id: int) -> list[dict]:
    return q("SELECT * FROM requirements WHERE service_id=? AND req_type='nonfunc' ORDER BY id",
             (service_id,))


def nfr_from_requirements(service_id: int, model: str = "") -> dict:
    """Черновик NFR & Security profile из НФТ-требований (LLM, fallback — таблица)."""
    svc = q1("SELECT * FROM services WHERE id=?", (service_id,))
    reqs = nonfunc_items(service_id)
    if not svc or not reqs:
        return None
    lst = "\n".join(f"- {r['ext_id']}: {r['text']}" for r in reqs)
    fallback = (f"## NFR & Security profile — {svc['name']} ({svc['code']})\n\n"
                "Сгенерировано из требований раздела «Требования» — проверьте и дополните:\n\n"
                "| Метрика | Значение |\n| --- | --- |\n"
                + "\n".join(f"| {r['ext_id']} | {r['text']} |" for r in reqs) + "\n\n"
                "### Модель угроз («Кто может украсть / сломать»)\n[TODO]\n")
    if not llm.configured():
        return {"provider": "fallback", "content_md": fallback,
                "note": "LLM не подключена — требования перенесены в таблицу без интерпретации"}
    user_prompt = (f"Составь раздел «NFR & Security profile» для сервиса "
                   f"{svc['name']} ({svc['code']}), тип проекта {svc['project_type']}.\n\n"
                   f"Нефункциональные требования от бизнеса:\n{lst}\n\n"
                   "Перенеси измеримые значения в таблицу метрик (RPS, время ответа p95, SLA, "
                   "масштабирование), сформируй модель угроз по этим требованиям; "
                   "недостающие значения пометь [TODO]. Markdown, по-русски, без вступлений.")
    try:
        text = llm.chat([{"role": "system", "content": DRAFT_SYSTEM},
                         {"role": "user", "content": user_prompt}],
                        temperature=0.3, max_tokens=4000, model=model)
        if not text.strip():
            raise llm.LLMError("LLM вернула пустой ответ")
        return {"provider": "ai-buddy", "model": (model or "").strip() or llm.config()[2],
                "content_md": text.strip(),
                "note": "AI-черновик NFR profile из НФТ — требует подтверждения автора (BR-28/BR-33)"}
    except llm.LLMError:
        return {"provider": "fallback", "content_md": fallback,
                "note": "LLM недоступна — требования перенесены в таблицу без интерпретации"}
