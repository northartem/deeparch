"""Проектирование: визуальная C4-модели (L1 Контекст, L2 Контейнеры).

Сценарии: (1) ручное рисование в редакторе (палитра, drag&drop, связи — как в Archi),
(2) AI-структура с последующим редактированием (BR-28, advisory).
Модель хранится как JSON (источник правды для редактора); экспорт в Mermaid C4
кладёт исходники диаграмм в артефакт vision_c4 — self-check и «Диаграммы» видят их.
"""
import json
import math
import re
from .db import q, q1, exec, now
from . import llm, ai

VIEWS = {"context": "Контекст (L1)", "container": "Контейнеры (L2)"}
_NODE_TYPES = {"person", "system", "external", "container", "db"}

AI_SYSTEM = """Ты архитектурный ассистент компании ДАТС. Спроектируй C4-модель архитектуры
сервиса и верни СТРОГО JSON вида:
{"nodes": [{"id":"n1","type":"person|system|external|container|db",
            "name":"...","desc":"...","tech":"...","x":кратные 40 координаты,"y":...}],
 "edges": [{"id":"e1","from":"n1","to":"n2","label":"что передаёт/зачем","tech":"HTTPS"}]}
Правила:
1. type: person — пользователь/актёр; system — проектируемый сервис; external — внешняя
   система; container — приложение/сервис внутри системы; db — база данных.
2. Опирайся на факты о сервисе и требования: каждый компонент, интеграция и требование
   должны быть отражены узлами/связями. Не придумывай лишнего.
3. Координаты: холст 960x560, элементы не должны перекрываться (шаг сетки 40px).
4. Только JSON, без пояснений."""


def load(service_id: int) -> dict:
    """Модели сервиса по видам: {context: {...}, container: {...}} (пустые — нормализованы)."""
    out = {}
    for view in VIEWS:
        row = q1("SELECT model_json, updated_by, updated_at FROM c4_models "
                 "WHERE service_id=? AND view=?", (service_id, view))
        if row:
            try:
                out[view] = normalize(json.loads(row["model_json"]))
            except (ValueError, TypeError):
                out[view] = {"nodes": [], "edges": []}
            out[view]["_updated_by"] = row["updated_by"]
            out[view]["_updated_at"] = row["updated_at"]
        else:
            out[view] = {"nodes": [], "edges": []}
    return out


_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")


def _new_id(kind: str, n: int, taken: set) -> str:
    """Свободный id вида n3/e7 (не повторяет уже занятые)."""
    nid = f"{kind}{n}"
    while nid in taken:
        n += 1
        nid = f"{kind}{n}"
    return nid


def normalize(model) -> dict:
    """Приводит модель к каноническому виду (гасит мусор от LLM/старых версий).

    id допускаются только [A-Za-z0-9_-]{1,40} — они попадают в SVG-атрибуты и в
    Mermaid-алиасы; битые/дублирующиеся id переименовываются, узлы не теряются.
    """
    m = model if isinstance(model, dict) else {}
    nodes, ids = [], set()
    for n in m.get("nodes") or []:
        nid = str(n.get("id") or "").strip()
        if not _ID_RE.fullmatch(nid) or nid in ids:
            nid = _new_id("n", len(nodes) + 1, ids)
        typ = n.get("type") if n.get("type") in _NODE_TYPES else "container"
        nodes.append({"id": nid, "type": typ,
                      "name": str(n.get("name") or "Без названия")[:80],
                      "desc": str(n.get("desc") or "")[:300],
                      "tech": str(n.get("tech") or "")[:80],
                      "x": _num(n.get("x"), 480), "y": _num(n.get("y"), 280)})
        ids.add(nid)
    edges, eids = [], set()
    for e in m.get("edges") or []:
        eid = str(e.get("id") or "").strip()
        if not _ID_RE.fullmatch(eid) or eid in eids:
            eid = _new_id("e", len(edges) + 1, eids)
        if e.get("from") not in ids or e.get("to") not in ids:
            continue
        edges.append({"id": eid, "from": e["from"], "to": e["to"],
                      "label": str(e.get("label") or "")[:80],
                      "tech": str(e.get("tech") or "")[:60]})
        eids.add(eid)
    return {"nodes": nodes, "edges": edges}


def _num(v, dflt):
    """Координата: число или значение по умолчанию; NaN/inf недопустимы —
    они ломают и JSON-ответ (ValueError при сериализации), и SVG (transform=translate(nan,…))."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return dflt
    return f if math.isfinite(f) else dflt


def save(service_id: int, view: str, model: dict, user: str) -> dict:
    if view not in VIEWS:
        raise ValueError(f"view должен быть: {', '.join(VIEWS)}")
    norm = normalize(model)
    if q1("SELECT id FROM c4_models WHERE service_id=? AND view=?", (service_id, view)):
        exec("UPDATE c4_models SET model_json=?, updated_by=?, updated_at=? "
             "WHERE service_id=? AND view=?",
             (json.dumps(norm, ensure_ascii=False), user, now(), service_id, view))
    else:
        exec("INSERT INTO c4_models(service_id,view,model_json,updated_by,updated_at) "
             "VALUES(?,?,?,?,?)",
             (service_id, view, json.dumps(norm, ensure_ascii=False), user, now()))
    return norm


def _alias(nid: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", nid) or "x"


def _esc_mmd(s: str) -> str:
    """Значение внутри кавычек Mermaid: кавычка → апостроф, перевод строки → разделитель
    (иначе строковый литерал разрывается и экспорт перестаёт парситься)."""
    return '"' + (s or "").replace("\r", " ").replace("\n", " · ").replace('"', "'") + '"'


def gen_mermaid(model: dict, view: str) -> str:
    """Экспорт модели в исходник Mermaid C4 (единый источник правды — исходник, не картинка)."""
    m = normalize(model)
    lines = ["C4Context" if view == "context" else "C4Container",
             "title " + ("System Context (L1)" if view == "context" else "Container diagram (L2)")]
    allowed = ({"person", "system", "external"} if view == "context"
               else {"person", "external", "container", "db", "system"})
    shown = [n for n in m["nodes"] if n["type"] in allowed]
    # алиасы уникальны: разные id ('u-1' и 'u_1') не должны склеиться в один элемент диаграммы
    aliases, used = {}, set()
    for n in shown:
        base = _alias(n["id"])
        if base[0].isdigit():
            base = "n" + base
        a, k = base, 2
        while a in used:
            a = f"{base}_{k}"
            k += 1
        used.add(a)
        aliases[n["id"]] = a
    for n in shown:
        a, name, desc, tech = aliases[n["id"]], _esc_mmd(n["name"]), _esc_mmd(n["desc"]), n["tech"] or "Технология"
        if n["type"] == "person":
            lines.append(f"Person({a}, {name}, {desc})")
        elif n["type"] == "system":
            lines.append(f"System({a}, {name}, {desc})")
        elif n["type"] == "external":
            lines.append(f"System_Ext({a}, {name}, {desc})")
        elif n["type"] == "db":
            lines.append(f"ContainerDb({a}, {name}, {_esc_mmd(tech)}, {desc})")
        else:
            lines.append(f"Container({a}, {name}, {_esc_mmd(tech)}, {desc})")
    seen = set()
    for e in m["edges"]:
        if e["from"] not in aliases or e["to"] not in aliases:
            continue
        key = (aliases[e["from"]], aliases[e["to"]])
        if key in seen:
            continue   # дубликат той же связи; обратная (B→A) — отдельная связь и сохраняется
        seen.add(key)
        tech = f', {_esc_mmd(e["tech"])}' if e["tech"] else ""
        lines.append(f'Rel({key[0]}, {key[1]}, {_esc_mmd(e["label"] or "взаимодействует")}{tech})')
    return "\n".join(lines)


def build_code(service_id: int) -> str:
    """Mermaid-исходник обеих моделей (для экспорта и предпросмотра)."""
    models = load(service_id)
    parts = []
    for view in ("context", "container"):
        if models[view]["nodes"]:
            parts.append(f"%% ===== {VIEWS[view]} =====\n" + gen_mermaid(models[view], view))
    return "\n\n".join(parts)


def export_to_artifact(service_id: int, user: str) -> dict:
    """Кладёт Mermaid-исходники обоих видов в diagram_code артефакта vision_c4."""
    code = build_code(service_id)
    art = q1("SELECT * FROM artifacts WHERE service_id=? AND kind='vision_c4'", (service_id,))
    if not art:
        return {"ok": False, "note": "Артефакт vision_c4 не найден"}
    if not code:
        exec("UPDATE artifacts SET diagram_code='', version=version+1, updated_by=?, "
             "updated_at=? WHERE id=?", (user, now(), art["id"]))
        return {"ok": True, "updated": False,
                "note": "Модели пусты — исходник диаграммы очищен"}
    exec("UPDATE artifacts SET diagram_code=?, version=version+1, updated_by=?, "
         "updated_at=? WHERE id=?", (code, user, now(), art["id"]))
    return {"ok": True, "updated": True, "code_len": len(code)}


def _fallback_model(service_id: int, view: str) -> dict:
    """Детерминированный старт: наша система + компоненты из каталога + пользователь."""
    svc = q1("SELECT * FROM services WHERE id=?", (service_id,))
    comps = q("SELECT c.name, c.kind FROM components c "
              "JOIN service_components sc ON sc.component_id=c.id WHERE sc.service_id=? "
              "LIMIT 8", (service_id,))
    nodes = [{"id": "n1", "type": "person", "name": "Пользователь", "desc": "", "tech": "", "x": 120, "y": 220},
             {"id": "n2", "type": "system", "name": f"{svc['name']} ({svc['code']})",
              "desc": "Проектируемая система", "tech": "", "x": 420, "y": 220}]
    edges = [{"id": "e1", "from": "n1", "to": "n2", "label": "использует", "tech": "HTTPS"}]
    if view == "container":
        nodes = nodes[1:]
        edges = []
        x = 120
        for i, c in enumerate(comps, 1):
            nodes.append({"id": f"c{i}", "type": "db" if (c["kind"] or "").lower() in ("db", "database")
                          else "container", "name": c["name"], "desc": "", "tech": "", "x": x, "y": 200})
            edges.append({"id": f"ec{i}", "from": "n2", "to": f"c{i}", "label": "включает", "tech": ""})
            x += 170
    return {"nodes": nodes, "edges": edges}


def ai_design(service_id: int, view: str, model: str = "") -> dict:
    """Сценарий 2: AI-структура — LLM проектирует C4-модель из фактов и требований."""
    if view not in VIEWS:
        raise ValueError(f"view должен быть: {', '.join(VIEWS)}")
    fallback = _fallback_model(service_id, view)
    if not llm.configured():
        return {"provider": "fallback", "model": None, "view": view, "model_json": fallback,
                "note": "LLM не подключена — стартовая структура по каталогу компонентов"}
    view_hint = ("Контекст (L1): только персоны, наш сервис и внешние системы."
                 if view == "context" else
                 "Контейнеры (L2): внутри нашего сервиса — контейнеры и БД; "
                 "снаружи — персоны и внешние системы.")
    user_prompt = (f"{view_hint}\n\nФакты о сервисе:\n{ai._service_facts(service_id)}\n\n"
                   f"Спроектируй {VIEWS[view]} для этого сервиса.")
    try:
        raw = llm.chat([{"role": "system", "content": AI_SYSTEM},
                        {"role": "user", "content": user_prompt}],
                       temperature=0.3, max_tokens=4000, model=model)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            raise llm.LLMError("LLM вернула не JSON")
        mj = normalize(json.loads(m.group(0)))
        if not mj["nodes"]:
            raise llm.LLMError("LLM вернула пустую модель")
        return {"provider": "ai-buddy", "model": (model or "").strip() or llm.config()[2],
                "view": view, "model_json": mj,
                "note": "AI-структура (AI-Buddy) — загрузите в редактор, проверьте и поправьте (advisory, BR-33)"}
    except (llm.LLMError, ValueError, KeyError, TypeError):
        return {"provider": "fallback", "model": None, "view": view, "model_json": fallback,
                "note": "LLM недоступна — стартовая структура по каталогу компонентов"}
