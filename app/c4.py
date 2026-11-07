"""Проектирование: визуальные модели (C4 L1 Контекст, L2 Контейнеры, ER Модель данных).

Сценарии: (1) ручное рисование в редакторе (палитра, drag&drop, связи — как в Archi),
(2) AI-структура с последующим редактированием (BR-28, advisory).
Модель хранится как JSON (источник правды для редактора); экспорт в Mermaid
синхронизируется в артефакты: L1/L2 → vision_c4, ER → data_model.
"""
import json
import math
import re

from . import ai, llm
from .db import exec, now, q, q1

VIEWS = {"context": "Контекст (L1)", "container": "Контейнеры (L2)",
         "er": "Модель данных (ER)"}
_NODE_TYPES = {"person", "system", "external", "container", "db"}

# кардинальности ER-связей: ключ — значение в модели, отображение — синтаксис Mermaid
ER_CARDS = {"1--1": "||--||", "1--n": "||--o{", "n--1": "}o--||", "n--m": "}o--o{"}
_ER_CARD_RE = re.compile(r"\}o--\|\||\|\|--o\{|\|\|--\|\||\}o--o\{")

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
    """Модели сервиса по видам: {context: {...}, container: {...}, er: {...}} (пустые — нормализованы)."""
    out = {}
    for view in VIEWS:
        row = q1("SELECT model_json, updated_by, updated_at FROM c4_models "
                 "WHERE service_id=? AND view=?", (service_id, view))
        if row:
            try:
                out[view] = normalize(json.loads(row["model_json"]), view)
            except (ValueError, TypeError):
                out[view] = _empty(view)
            out[view]["_updated_by"] = row["updated_by"]
            out[view]["_updated_at"] = row["updated_at"]
        else:
            out[view] = _empty(view)
    return out


def _empty(view: str) -> dict:
    return {"nodes": [], "edges": []}


_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")


def _new_id(kind: str, n: int, taken: set) -> str:
    """Свободный id вида n3/e7 (не повторяет уже занятые)."""
    nid = f"{kind}{n}"
    while nid in taken:
        n += 1
        nid = f"{kind}{n}"
    return nid


def normalize(model, view: str = "context") -> dict:
    """Приводит модель к каноническому виду (гасит мусор от LLM/старых версий).

    id допускаются только [A-Za-z0-9_-]{1,40} — они попадают в SVG-атрибуты и в
    Mermaid-алиасы; битые/дублирующиеся id переименовываются, узлы не теряются.
    Для ER-вида узел — сущность с атрибутами, связь несёт кардинальность.
    """
    if view == "er":
        return _normalize_er(model)
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


def _normalize_er(model) -> dict:
    """ER-модель: узел = сущность с атрибутами [{name, type, key: PK|FK|''}],
    связь = кардинальность (ER_CARDS) + подпись."""
    m = model if isinstance(model, dict) else {}
    nodes, ids = [], set()
    for n in m.get("nodes") or []:
        nid = str(n.get("id") or "").strip()
        if not _ID_RE.fullmatch(nid) or nid in ids:
            nid = _new_id("n", len(nodes) + 1, ids)
        attrs = []
        for a in (n.get("attrs") or [])[:16]:
            if not isinstance(a, dict):
                continue
            name = str(a.get("name") or "").strip()[:40]
            if not name:
                continue
            attrs.append({"name": name,
                          "type": str(a.get("type") or "").strip()[:24] or "varchar",
                          "key": a.get("key") if a.get("key") in ("PK", "FK") else ""})
        nodes.append({"id": nid, "type": "entity",
                      "name": str(n.get("name") or "Сущность")[:60],
                      "attrs": attrs,
                      "x": _num(n.get("x"), 480), "y": _num(n.get("y"), 280)})
        ids.add(nid)
    edges, eids = [], set()
    for e in m.get("edges") or []:
        eid = str(e.get("id") or "").strip()
        if not _ID_RE.fullmatch(eid) or eid in eids:
            eid = _new_id("e", len(edges) + 1, eids)
        if e.get("from") not in ids or e.get("to") not in ids:
            continue
        card = str(e.get("card") or "")
        if card in ER_CARDS:                 # модельная запись (1--n) → синтаксис Mermaid
            card = ER_CARDS[card]
        if not _ER_CARD_RE.fullmatch(card):
            card = ER_CARDS["1--n"]          # 1 к N — самый частый случай
        edges.append({"id": eid, "from": e["from"], "to": e["to"],
                      "card": card, "label": str(e.get("label") or "")[:60]})
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
    norm = normalize(model, view)
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
    """Экспорт модели в исходник Mermaid (единый источник правды — исходник, не картинка)."""
    if view == "er":
        return _gen_er(model)
    m = normalize(model, view)
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


def _er_entity_name(name: str, used: dict) -> str:
    """Имя сущности для Mermaid: читаемое; при коллизии — суффикс _2/_3."""
    base = name.strip() or "Сущность"
    n, out = 2, base
    while out in used:
        out = f"{base}_{n}"
        n += 1
    used[out] = True
    return out


def _er_ref(name: str) -> str:
    """Каноническая ссылка на сущность: простой токен как есть,
    имя со спецсимволами — в кавычках (Mermaid 11 понимает кавычки,
    но не % и \\ внутри них — заменяем на пробел)."""
    tok = _er_tok(name)
    if tok == name:
        return tok
    return _esc_mmd(re.sub(r"[%\\]", " ", name))


def _gen_er(model: dict) -> str:
    """ER-модель → erDiagram: сущности с атрибутами и связи с кардинальностью.
    Имена читаемые (Mermaid 11 рендерит кириллицу); спецсимволы — под кавычками."""
    m = _normalize_er(model)
    if not m["nodes"]:
        return ""
    names = _er_entity_names(m)
    lines = ["erDiagram"]
    for n in m["nodes"]:
        lines.append(f"    {_er_ref(names[n['id']])} {{")
        for a in n["attrs"]:
            key = f" {a['key']}" if a["key"] else ""
            lines.append(f"        {_er_tok(a['type'])} {_er_tok(a['name'])}{key}")
        lines.append("    }")
    for e in m["edges"]:
        if e["from"] not in names or e["to"] not in names:
            continue
        lines.append(f"    {_er_ref(names[e['from']])} {e['card']} "
                     f"{_er_ref(names[e['to']])} : {_esc_mmd(e['label'] or 'относится к')}")
    return "\n".join(lines)


def _er_entity_names(m: dict) -> dict:
    """id → уникальное читаемое имя сущности (коллизии гасятся суффиксом)."""
    used, out = {}, {}
    for n in m["nodes"]:
        out[n["id"]] = _er_entity_name(n["name"], used)
    return out


def _er_tok(s: str) -> str:
    """Токен вне кавычек erDiagram: без пробелов и кавычек."""
    return re.sub(r'[\s"\']', "_", s.strip()) or "x"


def build_code(service_id: int) -> str:
    """Mermaid-исходник обеих моделей (для экспорта и предпросмотра)."""
    models = load(service_id)
    parts = []
    for view in ("context", "container"):
        if models[view]["nodes"]:
            parts.append(f"%% ===== {VIEWS[view]} =====\n" + gen_mermaid(models[view], view))
    return "\n\n".join(parts)


def validate_models(service_id: int) -> dict:
    """Валидация перед экспортом: детерминированные проверки без LLM.
    blockers — экспорт бессмыслен/опасен (409 без force), warnings — на усмотрение автора."""
    models = load(service_id)
    l1, l2 = models["context"], models["container"]
    blockers, warnings = [], []
    if not l1["nodes"] and not l2["nodes"]:
        blockers.append("обе модели пусты — экспорт затрёт исходник диаграммы")
    else:
        if not l1["nodes"]:
            warnings.append("Контекст (L1) пуст — экспортируются только контейнеры")
        elif not any(n["type"] == "system" for n in l1["nodes"]):
            blockers.append("в контексте (L1) нет нашего сервиса — нужен узел типа «система»")
        if not any(n["type"] == "person" for n in l1["nodes"]):
            warnings.append("в контексте (L1) нет ни одной персоны (пользователя/актора)")
        if l1["nodes"] and not l2["nodes"]:
            warnings.append("контейнеры (L2) не нарисованы — на ревью обычно спрашивают внутреннее устройство")
    for view, m in (("context", l1), ("container", l2)):
        ids = {n["id"] for n in m["nodes"]}
        dangling = [e for e in m["edges"] if e["from"] not in ids or e["to"] not in ids]
        if dangling:
            blockers.append(f"{VIEWS[view]}: {len(dangling)} связей ссылаются на несуществующие узлы")
        isolated = [n["name"] for n in m["nodes"]
                    if not any(e["from"] == n["id"] or e["to"] == n["id"] for e in m["edges"])]
        if isolated and ids:
            warnings.append(f"{VIEWS[view]}: узлы без связей — "
                            f"{', '.join(isolated[:5])}" + ("…" if len(isolated) > 5 else ""))
    return {"blockers": blockers, "warnings": warnings}


def validate_er(model: dict) -> dict:
    """Детерминированная проверка ER-модели (структурная; содержательность — за автором)."""
    m = _normalize_er(model)
    blockers, warnings = [], []
    ids = {n["id"] for n in m["nodes"]}
    dangling = [e for e in m["edges"] if e["from"] not in ids or e["to"] not in ids]
    if dangling:
        blockers.append(f"ER: {len(dangling)} связей ссылаются на несуществующие сущности")
    nokey = [n["name"] for n in m["nodes"]
             if not any(a["key"] == "PK" for a in n["attrs"])]
    if nokey:
        warnings.append("ER: сущности без первичного ключа — "
                        + ", ".join(nokey[:5]) + ("…" if len(nokey) > 5 else ""))
    isolated = [n["name"] for n in m["nodes"]
                if not any(e["from"] == n["id"] or e["to"] == n["id"] for e in m["edges"])]
    if isolated and ids:
        warnings.append("ER: сущности без связей — " + ", ".join(isolated[:5])
                        + ("…" if len(isolated) > 5 else ""))
    return {"blockers": blockers, "warnings": warnings}


def sync_data_model(service_id: int) -> dict:
    """ER-аналог sync_vision: JSON ER-модель — источник правды, erDiagram в артефакте
    data_model — производная. Пустая модель исходник не затирает; при блокерах
    («связи на несуществующие сущности») запись не выполняется."""
    er = load(service_id)["er"]
    report = validate_er(er)
    if report["blockers"]:
        return {"synced": False, "code": None, "skipped": report["blockers"]}
    code = gen_mermaid(er, "er")
    if not code:
        return {"synced": False, "code": None, "skipped": []}
    art = q1("SELECT id, diagram_code FROM artifacts WHERE service_id=? AND kind='data_model'",
             (service_id,))
    if not art or (art["diagram_code"] or "") == code:
        return {"synced": False, "code": code, "skipped": []}
    exec("UPDATE artifacts SET diagram_code=? WHERE id=?", (code, art["id"]))
    return {"synced": True, "code": code, "skipped": []}


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


def sync_vision(service_id: int) -> dict:
    """Авто-синхронизация: JSON-модель — источник правды архитектуры (решение 2026-11-07),
    Mermaid-исходник в артефакте vision_c4 — производная. Вызывается при каждом сохранении
    вида из редактора; версию артефакта не поднимает (версия — история ручных правок
    документа) и пустыми моделями исходник не затирает.

    Валидация уважается и при автосохранении: при блокирующих проблемах модели
    («в L1 нет нашего сервиса», «обе модели пусты») запись НЕ выполняется — иначе
    невалидная производная закрыла бы пункты готовности формально. Причины возврата
    в skipped — редактор показывает их в статус-чипе.
    Возвращает {synced, code, skipped}: code — актуальный исходник (для обновления
    галереи без перезагрузки)."""
    report = validate_models(service_id)
    if report["blockers"]:
        return {"synced": False, "code": None, "skipped": report["blockers"]}
    code = build_code(service_id)
    if not code:
        return {"synced": False, "code": None, "skipped": []}
    art = q1("SELECT id, diagram_code FROM artifacts WHERE service_id=? AND kind='vision_c4'",
             (service_id,))
    if not art or (art["diagram_code"] or "") == code:
        return {"synced": False, "code": code, "skipped": []}
    exec("UPDATE artifacts SET diagram_code=? WHERE id=?", (code, art["id"]))
    return {"synced": True, "code": code, "skipped": []}


def _fallback_model(service_id: int, view: str) -> dict:
    """Детерминированный старт: наша система + компоненты из каталога + пользователь;
    для ER — сущности из БД-узлов уже сохранённого L2 (каскад L2 → ER)."""
    svc = q1("SELECT * FROM services WHERE id=?", (service_id,))
    comps = q("SELECT c.name, c.kind FROM components c "
              "JOIN service_components sc ON sc.component_id=c.id WHERE sc.service_id=? "
              "LIMIT 8", (service_id,))
    if view == "er":
        ents = []
        for c in comps:
            if "db" in (c["kind"] or "").lower() or "дан" in (c["name"] or "").lower():
                ents.append({"id": f"n{len(ents) + 1}", "type": "entity",
                             "name": c["name"] or f"Сущность{len(ents) + 1}",
                             "attrs": [{"name": "id", "type": "uuid", "key": "PK"}],
                             "x": 120 + len(ents) * 240, "y": 240})
        l2 = load(service_id)["container"]
        for n in l2["nodes"]:
            if n["type"] == "db" and len(ents) < 6:
                ents.append({"id": f"n{len(ents) + 1}", "type": "entity", "name": n["name"],
                             "attrs": [{"name": "id", "type": "uuid", "key": "PK"}],
                             "x": 120 + len(ents) * 240, "y": 240})
        if not ents:
            ents = [{"id": "n1", "type": "entity", "name": "Сущность 1 [TODO]",
                     "attrs": [{"name": "id", "type": "uuid", "key": "PK"}], "x": 200, "y": 240},
                    {"id": "n2", "type": "entity", "name": "Сущность 2 [TODO]",
                     "attrs": [{"name": "id", "type": "uuid", "key": "PK"}], "x": 520, "y": 240}]
        edges = [{"id": "e1", "from": ents[0]["id"], "to": ents[1]["id"],
                  "card": ER_CARDS["1--n"], "label": "[TODO] связь"}] if len(ents) > 1 else []
        return {"nodes": ents, "edges": edges}
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


def _l1_context(service_id: int) -> str:
    """Каскад L1→L2: сохранённая модель контекста как вход для проектирования контейнеров."""
    row = q1("SELECT model_json FROM c4_models WHERE service_id=? AND view='context'", (service_id,))
    if not row:
        return ""
    try:
        mj = json.loads(row["model_json"])
    except (ValueError, TypeError):
        return ""
    nodes = [n for n in (mj.get("nodes") or []) if isinstance(n, dict)]
    if not nodes:
        return ""
    lines = ["Сохранённая модель контекста (L1) — L2 должен быть согласован с ней:",
             "- участники: " + "; ".join(
                 f"{n.get('name', '?')} ({n.get('type', 'system')})" for n in nodes)]
    edges = [e for e in (mj.get("edges") or []) if isinstance(e, dict)]
    if edges:
        names = {n.get("id"): n.get("name", "?") for n in nodes}
        lines.append("- связи: " + "; ".join(
            f"{names.get(e.get('from'), e.get('from'))} → "
            f"{names.get(e.get('to'), e.get('to'))}"
            + (f" ({e['label']})" if e.get("label") else "") for e in edges))
    return "\n".join(lines)


ER_SYSTEM = """Ты архитектурный ассистент компании ДАТС. Спроектируй ER-модель данных
и верни СТРОГО JSON вида:
{"nodes": [{"id":"n1","name":"Сущность",
            "attrs":[{"name":"id","type":"uuid","key":"PK"}],
            "x":кратные 40 координаты,"y":...}],
 "edges": [{"id":"e1","from":"n1","to":"n2","card":"1--1|1--n|n--1|n--m","label":"смысл связи"}]}
Правила:
1. Сущности выводи из требований и API-спецификации — не придумывай лишнего; ключи (PK/FK) ставь осмысленно.
2. Связи: 1--n — «один ко многим» (самая частая), 1--1, n--1, n--m — многие ко многим.
3. Атрибуты: 2-6 ключевых полей на сущность (id, ссылки, статусные/бизнес-поля); типы: uuid, varchar, int, decimal, datetime, bool, jsonb.
4. Координаты: холст 960x560, элементы не должны перекрываться (шаг сетки 40px).
5. Только JSON, без пояснений."""


def ai_design(service_id: int, view: str, model: str = "") -> dict:
    """Сценарий 2: AI-структура — LLM проектирует модель из фактов и требований.
    Для L2 вход дополнен сохранённой L1 (каскад), для ER — L2 и API-спецификацией."""
    if view not in VIEWS:
        raise ValueError(f"view должен быть: {', '.join(VIEWS)}")
    fallback = _fallback_model(service_id, view)
    if not llm.configured():
        return {"provider": "fallback", "model": None, "view": view, "model_json": fallback,
                "note": "LLM не подключена — стартовая структура по каталогу компонентов"}
    if view == "er":
        return _ai_er(service_id, model, fallback)
    view_hint = ("Контекст (L1): только персоны, наш сервис и внешние системы."
                 if view == "context" else
                 "Контейнеры (L2): внутри нашего сервиса — контейнеры и БД; "
                 "снаружи — персоны и внешние системы.")
    l1 = _l1_context(service_id) if view == "container" else ""
    parts = [view_hint]
    if l1:
        parts.append(l1)
    parts += [f"Факты о сервисе:\n{ai._service_facts(service_id)}",
              f"Спроектируй {VIEWS[view]} для этого сервиса."]
    user_prompt = "\n\n".join(parts)
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


def _ai_er(service_id: int, model: str, fallback: dict) -> dict:
    """AI-каскад для ER: сущности выводятся из API-спецификации и требований;
    L2-модель (БД-узлы) задаёт согласованность с уже спроектированными хранилищами."""
    l2 = load(service_id)["container"]
    dbs = [n["name"] for n in l2["nodes"] if n["type"] == "db"]
    parts = []
    if dbs:
        parts.append("Хранилища из сохранённой L2 (сущности должны их покрывать): "
                     + ", ".join(dbs))
    api_art = q1("SELECT content_md FROM artifacts WHERE service_id=? AND kind='api'",
                 (service_id,))
    if api_art and (api_art["content_md"] or "").strip():
        parts.append("API-спецификация (источник сущностей и полей):\n"
                     + api_art["content_md"].strip()[:2500])
    parts += [f"Факты о сервисе:\n{ai._service_facts(service_id)}",
              "Спроектируй ER-модель данных (Модель данных (ER)) для этого сервиса."]
    try:
        raw = llm.chat([{"role": "system", "content": ER_SYSTEM},
                        {"role": "user", "content": "\n\n".join(parts)}],
                       temperature=0.3, max_tokens=4000, model=model)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            raise llm.LLMError("LLM вернула не JSON")
        mj = _normalize_er(json.loads(m.group(0)))
        if not mj["nodes"]:
            raise llm.LLMError("LLM вернула пустую модель")
        return {"provider": "ai-buddy", "model": (model or "").strip() or llm.config()[2],
                "view": "er", "model_json": mj,
                "note": "AI-структура (AI-Buddy) — загрузите в редактор, проверьте и поправьте (advisory, BR-33)"}
    except (llm.LLMError, ValueError, KeyError, TypeError):
        return {"provider": "fallback", "model": None, "view": "er", "model_json": fallback,
                "note": "LLM недоступна — стартовая структура по каталогу компонентов"}
