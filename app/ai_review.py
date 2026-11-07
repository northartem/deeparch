"""AI-ревью архитектурного пакета ДО отправки на ревью (advisory, BR-33).

Use case: автор (team_lead) прогоняет ревью перед отправкой, чтобы исправить
находки заранее и не получать changes_requested с первого раза. Выводы advisory —
ничего не блокируют, решение за автором.

Два слоя:
1. Формальный (детерминированный, без LLM, <1 с): полнота по матрице типа проекта,
   карточка, NFR-цели в цифрах, C4-модели, покрытие требований. Поглощает AI Gate —
   mock-эвристика predict_checklist (BR-29) упразднена.
2. Содержательный (LLM AI-Buddy): противоречия между артефактами, риски,
   незакрытые требования, расхождения C4 и текста.
"""
import json
import re

from . import c4 as c4mod
from . import llm, nfr, reqs
from .db import exec, now, q, q1
from .standards import ARTIFACT_KINDS, PROJECT_TYPES

_TITLES = {a["kind"]: a["title"] for a in ARTIFACT_KINDS}
_LLM_KINDS = ("противоречие", "риск", "пробел", "несоответствие")

REVIEW_SYSTEM = """Ты опытный архитектурный ревьюер компании ДАТС. Проведи предварительное
ревью архитектурного пакета сервиса ДО его отправки эксперту и верни СТРОГО JSON-объект:
{"findings": [{"kind": "противоречие" | "риск" | "пробел" | "несоответствие",
               "artifact_kind": "vision_c4|adr|deployment|api|data_model|nfr_security|config_build|threat_model|drp_bcp или null",
               "severity": "warning" | "info",
               "title": "краткий заголовок находки",
               "detail": "что не так и почему это заметит ревьюер (1-3 предложения)",
               "evidence": "цитата или факт из пакета, на котором основана находка"}]}
Правила:
1. Опирайся только на предоставленные данные; не выдумывай артефакты, требования и факты.
2. Ищи содержательные проблемы: противоречия между артефактами, незакрытые требования,
   NFR без цифр, расхождения C4-модели и текста, пробелы в Security/DRP.
3. Не дублируй формальные проверки — пустые и необязательные артефакты уже проверены системой.
4. Максимум 6 находок, самые важные сначала; содержательных находок может не быть — пустой массив.
5. Пиши компактно: title до 80 символов, detail до 2 предложений, evidence — одна цитата.
6. Только JSON без markdown-ограждений и пояснений. Все тексты — по-русски.
7. Находки advisory (BR-33): ты помогаешь автору, решение всегда за человеком."""


def _f(severity, kind, title, detail="", target=None, artifact_kind=None,
       evidence=None, layer="formal"):
    return {"severity": severity, "layer": layer, "kind": kind,
            "artifact_kind": artifact_kind,
            "artifact": _TITLES.get(artifact_kind),   # русское название для UI
            "title": title, "detail": detail,
            "evidence": evidence, "target": target}


def _tgt(sid, tab):
    return f"#/service/{sid}/{tab}"


def _filled(a) -> bool:
    return bool(a and ((a["content_md"] or "").strip() or (a["diagram_code"] or "").strip()))


def formal_findings(svc) -> list[dict]:
    """Слой 1: детерминированные проверки без LLM. Warning — заметит ревьюер,
    info — желательно поправить."""
    sid = svc["id"]
    matrix = PROJECT_TYPES.get(svc["project_type"], {}).get("matrix", {})
    arts = {a["kind"]: a for a in q("SELECT * FROM artifacts WHERE service_id=?", (sid,))}
    out = []
    # 1. Полнота по матрице типа проекта + ссылки на исходники (бывший AI Gate, пункт «Ch»)
    for a in ARTIFACT_KINDS:
        status = matrix.get(a["kind"])
        if status is None:
            continue
        row = arts.get(a["kind"])
        if not _filled(row):
            if status == "mandatory":
                out.append(_f("warning", "пробел",
                              f"Обязательный артефакт «{a['title']}» пуст",
                              "Не заполнен, хотя матрица типа проекта требует его — gate не пропустит отправку.",
                              _tgt(sid, "artifacts"), a["kind"]))
            elif status == "desired":
                out.append(_f("info", "пробел",
                              f"Желательный артефакт «{a['title']}» пуст",
                              "Матрица типа проекта помечает его желательным — на ревью могут спросить.",
                              _tgt(sid, "artifacts"), a["kind"]))
        elif row["source_url"]:
            pass
        else:
            out.append(_f("info", "несоответствие",
                          f"«{a['title']}»: нет ссылки на исходник",
                          "Артефакт заполнен, но source_url не указан — ревьюер не сможет сверить с первоисточником.",
                          _tgt(sid, "artifacts"), a["kind"]))
        # 2. Обязательные диаграммные виды: контент есть, диаграммы нет
        if status == "mandatory" and _filled(row) and a["kind"] in ("deployment", "data_model") \
                and not (row["diagram_code"] or "").strip():
            out.append(_f("info", "пробел",
                          f"«{a['title']}»: нет диаграммы",
                          "Текст заполнен, но Mermaid-исходник диаграммы пуст — на ревью диаграмму обычно спрашивают.",
                          _tgt(sid, "artifacts"), a["kind"]))
        # 3. NFR-цели должны быть в цифрах (BR-51)
        if a["kind"] == "nfr_security" and _filled(row):
            ex = nfr.extract_targets(sid)
            if ex["artifact_present"] and not ex["extracted"]:
                out.append(_f("warning", "пробел",
                              "NFR-цели не выражены в цифрах",
                              "В артефакте NFR & Security не найдено ни одной цели RPS/p95/SLA/RTO/RPO в числовом виде.",
                              _tgt(sid, "nfr"), "nfr_security"))
    # 4. Карточка сервиса
    missing_card = [lbl for lbl, v in (("владелец", svc["owner"]), ("домен", svc["domain"]))
                    if not (v or "").strip()]
    if missing_card:
        out.append(_f("warning", "пробел", "Карточка сервиса заполнена не полностью",
                      "Не указаны: " + ", ".join(missing_card) + ".",
                      _tgt(sid, "card")))
    # 5. C4-модели (детерминированная валидация «Проектирования»)
    v = c4mod.validate_models(sid)
    c4_blockers = [b for b in v["blockers"] if "обе модели пусты" not in b]  # покрыто пунктом vision_c4
    for b in c4_blockers:
        out.append(_f("warning", "несоответствие", f"C4: {b}",
                      "Структурная проблема модели — ревьюер обычно просит её исправить до решения.",
                      _tgt(sid, "design")))
    for w in v["warnings"]:
        out.append(_f("info", "несоответствие", f"C4: {w}", target=_tgt(sid, "design")))
    # 6. Покрытие требований (covered_by) — без LIMIT: считаем честно по всем
    reqs_rows = q("SELECT id, req_type, ext_id FROM requirements WHERE service_id=?"
                  " ORDER BY req_type, id", (sid,))
    cov = reqs.coverage(sid)
    uncovered = [r for r in reqs_rows if not cov.get(r["id"])]
    if uncovered and reqs_rows:
        names = [f"{r['ext_id'] or ('НФТ' if r['req_type'] == 'nonfunc' else 'ФТ')}" for r in uncovered][:6]
        out.append(_f("warning", "пробел",
                      f"Требования без покрытия: {len(uncovered)} из {len(reqs_rows)}",
                      "Не прослеживаются в артефактах (covered_by пуст): " + ", ".join(names)
                      + ("…" if len(uncovered) > 6 else "") + ".",
                      _tgt(sid, "reqs")))
    return out


def _review_context(service_id: int) -> str:
    """Полный контекст пакета для LLM-ревью: карточка, требования, C4, содержимое артефактов."""
    svc = q1("SELECT * FROM services WHERE id=?", (service_id,))
    lines = [(f"Сервис: {svc['name']} ({svc['code']}), домен: {svc['domain'] or '—'}, "
              f"тип проекта: {svc['project_type']}, владелец: {svc['owner'] or '—'}.")]
    reqs_rows = q("SELECT req_type, ext_id, text FROM requirements WHERE service_id=?"
                  " ORDER BY req_type, id LIMIT 30", (service_id,))
    if reqs_rows:
        lines.append("Требования:")
        lines += [f"- {r['ext_id'] or ('НФТ' if r['req_type'] == 'nonfunc' else 'ФТ')}: {r['text']}"
                  for r in reqs_rows]
    for view, title in (("context", "C4 контекст (L1)"), ("container", "C4 контейнеры (L2)")):
        model = c4mod.load(service_id)[view]          # нормализация + защита от битого JSON
        nodes, edges = model.get("nodes", []), model.get("edges", [])
        if nodes:
            lines.append(f"{title}: узлы — " + "; ".join(
                f"{n.get('type', '?')} {n.get('name', '?')}" for n in nodes[:15]))
            if edges:
                names = {n["id"]: n.get("name", n["id"]) for n in nodes}
                lines.append(f"{title}: связи — " + "; ".join(
                    f"{names.get(e['from'], e['from'])} → {names.get(e['to'], e['to'])}"
                    + (f" ({e['label']})" if e.get("label") else "")
                    for e in edges[:15]))
    for a in q("SELECT kind, content_md, diagram_code FROM artifacts WHERE service_id=?"
               " ORDER BY kind", (service_id,)):
        body = (a["content_md"] or "").strip()
        if not body and not (a["diagram_code"] or "").strip():
            continue
        chunk = body[:1200] if body else f"[только диаграмма]\n{(a['diagram_code'] or '').strip()[:600]}"
        lines.append(f"=== Артефакт «{_TITLES.get(a['kind'], a['kind'])}» ===\n{chunk}")
    return "\n\n".join(lines)


def _parse_findings_json(raw: str) -> dict | None:
    """Разбор ответа LLM; ответ мог обрезаться лимитом токенов — собираем JSON
    из завершённых находок (санитизация хвоста)."""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except ValueError:
            pass
    start = raw.find("{")
    if start < 0:
        return None
    ends = [mm.end() for mm in re.finditer(r"\}", raw)]
    for end in reversed(ends):                     # от самой длинной законченной находки
        cand = raw[start:end].rstrip().rstrip(",") + "]}"
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict) and "findings" in obj:
                return obj
        except ValueError:
            continue
    return None


def _normalize_llm_findings(raw) -> list[dict]:
    """Приводит ответ LLM к безопасной форме находок; мусор отбрасывается."""
    if not isinstance(raw, dict):
        return []
    out = []
    for it in (raw.get("findings") or [])[:6]:
        if not isinstance(it, dict):
            continue
        title = (it.get("title") or "").strip()
        detail = (it.get("detail") or "").strip()
        if not (title or detail):
            continue
        out.append(_f(
            it.get("severity") if it.get("severity") in ("warning", "info") else "info",
            it.get("kind") if it.get("kind") in _LLM_KINDS else "пробел",
            title[:200] or "Находка ревью",
            detail[:800],
            None,
            it.get("artifact_kind") if it.get("artifact_kind") in _TITLES else None,
            (it.get("evidence") or "").strip()[:400] or None,
            layer="llm"))
    return out


def llm_findings(service_id: int, model: str = "") -> dict:
    """Слой 2: содержательное ревью пакета одним LLM-вызовом (advisory)."""
    if not llm.configured():
        return {"provider": "none", "model": None, "findings": [],
                "note": "LLM не подключена — выполнены только формальные проверки"}
    prompt = (f"Архитектурный пакет сервиса для предварительного ревью:\n\n"
              f"{_review_context(service_id)}\n\n"
              f"Проведи ревью и верни JSON с находками.")
    try:
        raw = llm.chat([{"role": "system", "content": REVIEW_SYSTEM},
                        {"role": "user", "content": prompt}],
                       temperature=0.2, max_tokens=3500, model=model)
        obj = _parse_findings_json(raw)
        if obj is None:
            raise llm.LLMError("в ответе нет корректного JSON с находками")
        findings = _normalize_llm_findings(obj)
        for f in findings:  # цель находки: артефакт → «Артефакты», остальное → карточка
            f["target"] = _tgt(service_id, "artifacts") if f["artifact_kind"] else _tgt(service_id, "card")
        return {"provider": "ai-buddy",
                "model": (model or "").strip() or llm.config()[2],
                "findings": findings, "note": None}
    except (llm.LLMError, ValueError, KeyError, TypeError) as e:
        return {"provider": "fallback", "model": None, "findings": [],
                "note": f"LLM недоступна ({e}) — выполнены только формальные проверки"}


def run(service_id: int, created_by: str, model: str = "") -> dict | None:
    """Прогон AI-ревью: слой 1 + слой 2, результат сохраняется в историю."""
    svc = q1("SELECT * FROM services WHERE id=?", (service_id,))
    if not svc:
        return None
    formal = formal_findings(svc)
    llm_res = llm_findings(service_id, model=model)
    findings = formal + llm_res["findings"]
    prev = q1("SELECT id, formal_count, llm_count, created_at FROM ai_review_runs "
              "WHERE service_id=? ORDER BY id DESC LIMIT 1", (service_id,))
    ts = now()
    rid = exec("INSERT INTO ai_review_runs(service_id,findings,formal_count,llm_count,"
               "provider,model,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
               (service_id, json.dumps(findings, ensure_ascii=False), len(formal),
                len(llm_res["findings"]), llm_res["provider"], llm_res["model"],
                created_by, ts))
    return {"id": rid, "service_id": service_id, "findings": findings,
            "formal_count": len(formal), "llm_count": len(llm_res["findings"]),
            "provider": llm_res["provider"], "model": llm_res["model"],
            "note": llm_res.get("note"), "created_by": created_by, "created_at": ts,
            "previous": ({"id": prev["id"],
                          "total": prev["formal_count"] + prev["llm_count"],
                          "created_at": prev["created_at"]} if prev else None)}


def last(service_id: int) -> dict | None:
    rows = q("SELECT * FROM ai_review_runs WHERE service_id=? ORDER BY id DESC LIMIT 2",
             (service_id,))
    if not rows:
        return None
    row = rows[0]
    try:
        findings = json.loads(row["findings"])
    except (ValueError, TypeError):
        findings = []
    prev = rows[1] if len(rows) > 1 else None
    return {"id": row["id"], "service_id": row["service_id"], "findings": findings,
            "formal_count": row["formal_count"], "llm_count": row["llm_count"],
            "provider": row["provider"], "model": row["model"],
            "created_by": row["created_by"], "created_at": row["created_at"],
            "previous": ({"id": prev["id"],
                          "total": prev["formal_count"] + prev["llm_count"],
                          "created_at": prev["created_at"]} if prev else None)}
