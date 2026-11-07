"""
Интеграционный слой с каталогом/CMDB (BR-20…BR-23).

Абстракция CatalogAdapter: пока реализован MockBackstageAdapter.
В проде — модуль @backstage/plugin-catalog-backend-module-gitlab читает
catalog-info.yaml из GitLab; DataGerry — через REST API (pageId=915904198).
"""
from .db import exec, now, q, q1

MOCK_CATALOG = [
    {
        "metadata": {"name": "iq-express", "title": "IQ.express", "owner": "d.prusov"},
        "spec": {"type": "service", "domain": "Logistics", "lifecycle": "production",
                 "dependsOn": ["component:default/ecs-logging"]},
    },
    {
        "metadata": {"name": "switcherry-mc", "title": "Switcherry (MC) backend", "owner": "d.demidov"},
        "spec": {"type": "service", "domain": "Mobile", "lifecycle": "production", "dependsOn": []},
    },
    {
        "metadata": {"name": "aibuddy-metamodel", "title": "AIBuddy Metamodel Platform", "owner": "a.lobanok"},
        "spec": {"type": "service", "domain": "AI", "lifecycle": "development", "dependsOn": []},
    },
]


def import_from_backstage(dry_run: bool = True):
    created, skipped = [], []
    for entity in MOCK_CATALOG:
        code = entity["metadata"]["name"].upper().replace("-", "_")[:12]
        exists = q1("SELECT id FROM services WHERE code=?", (code,))
        if exists:
            skipped.append({"code": code, "reason": "уже в реестре"})
            continue
        if dry_run:
            created.append({"code": code, "name": entity["metadata"]["title"], "dry_run": True})
            continue
        sid = exec(
            "INSERT INTO services(code,name,domain,owner,architect,project_type,lifecycle,review_status,catalog_source,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (code, entity["metadata"]["title"], entity["spec"].get("domain"),
             entity["metadata"].get("owner"), entity["metadata"].get("owner"),
             "mvp", entity["spec"].get("lifecycle", "design"), "draft", "backstage-mock", now(), now()))
        created.append({"code": code, "id": sid})
    return {"source": "backstage-mock", "created": created, "skipped": skipped}


def sync_to_catalog(service_id: int):
    """Публикация архитектурных атрибутов сервиса в каталог (BR-21, mock)."""
    svc = q1("SELECT * FROM services WHERE id=?", (service_id,))
    if not svc:
        return None
    arts = q("SELECT kind, source_url FROM artifacts WHERE service_id=?", (service_id,))
    payload = {
        "apiVersion": "backstage.io/v1alpha1",
        "kind": "Component",
        "metadata": {"name": svc["code"].lower(), "title": svc["name"], "owner": svc["owner"]},
        "spec": {
            "type": "service", "lifecycle": svc["lifecycle"], "domain": svc["domain"],
            "deeparch": {
                "review_status": svc["review_status"],
                "project_type": svc["project_type"],
                "artifacts": {a["kind"]: a["source_url"] for a in arts if a["source_url"]},
            },
        },
    }
    return {"service_id": service_id, "catalog_entity": payload, "generated": "catalog-info.yaml (mock)"}


# ---------- синхронизация реестра техдолга с Confluence (MVP2 BR-54…56) ----------
# Источник правила: «Реестр технического долга» (pageId=915912594) — реестр ведётся
# в Confluence; DeepArch экспортирует/импортирует таблицу реестра.

DEBT_PAGE_ID = "915912594"


def export_debts_xhtml(service_id: int = None):
    """Экспорт реестра долга в XHTML (storage format Confluence) — таблица реестра."""
    import html as _html
    where, args = "", []
    if service_id:
        where = " WHERE d.service_id=?"
        args = [service_id]
    rows = q("SELECT d.*, s.code AS service_code FROM tech_debts d"
             " LEFT JOIN services s ON s.id=d.service_id" + where +
             " ORDER BY d.debt_id", tuple(args))
    th = ["ID", "Тип", "Название", "Система", "Описание", "Причина", "Целевое состояние",
          "Риск", "Вероятность", "Ущерб", "Владелец", "Приоритет", "Статус",
          "План погашения", "Зависимости"]
    cells = "".join(f"<th>{h}</th>" for h in th)
    trs = []
    for d in rows:
        vals = [d["debt_id"], d["dtype"], d["title"], d["service_code"] or "—",
                d["description"], d["cause"], d["target_state"], d["risk"],
                d["probability"], d["damage"], d["owner"] or "—", d["priority"],
                d["status"], d["repayment_plan"], d["dependencies"]]
        tds = "".join(f"<td>{_html.escape(str(v or ''))}</td>" for v in vals)
        trs.append(f"<tr>{tds}</tr>")
    xhtml = (f"<p>Реестр технического долга — выгрузка из DeepArch "
             f"({len(rows)} записей). Формат по стандарту DA: pageId={DEBT_PAGE_ID}.</p>"
             f"<table><tbody><tr>{cells}</tr>{''.join(trs)}</tbody></table>")
    return {"page_id": DEBT_PAGE_ID, "records": len(rows), "xhtml": xhtml}


def parse_debts_markdown(text: str):
    """Импорт реестра долга из markdown-таблицы страницы Confluence.

    Понимает таблицу стандарта («Реестр технического долга», pageId=915912594):
    | ID | Тип долга | Название | ... | Приоритет | Статус | ...
    ID сохраняется как есть (правило pageId=918365931: ID неизменяем и
    не переиспользуется) — при конфликте запись обновляется, а не создаётся заново.
    """
    from .standards import DEBT_RISKS, DEBT_STATUSES
    header, parsed = None, []
    for line in text.splitlines():
        line = line.strip().strip("|").strip()
        if not line or set(line.replace("|", "").strip()) <= set("-: "):
            continue
        cells = [c.strip().strip("*").strip() for c in line.split("|")]
        if header is None:
            if any("ID" in c for c in cells):
                header = cells
            continue
        row = dict(zip(header, cells, strict=False))
        did = (row.get("ID") or row.get("id") or "").strip()
        if not did:
            continue
        dtype = "AD" if "AD" in did.split("-")[0].upper() else "TD"
        title = row.get("Название") or row.get("Название долга") or ""
        if not title:
            continue
        risk_raw = row.get("Риск", "")
        risk = next((r for r in DEBT_RISKS if r.lower() == risk_raw.strip().lower()),
                    "Medium")
        prio = row.get("Приоритет", "P2").strip().upper()
        if prio not in ("P0", "P1", "P2", "P3"):
            prio = "P2"
        status_raw = (row.get("Статус") or "").strip().lower()
        ru_status = {"новый": "new", "принят": "accepted", "запланирован": "planned",
                     "в работе": "in_progress", "погашен": "repaid", "отменён": "cancelled"}
        status = ru_status.get(status_raw) or \
                 next((s for s in DEBT_STATUSES if s.startswith(status_raw[:5])
                       and status_raw), "new")
        def _num(key, default=3, row=row):   # row фиксируется: замыкание не должно видеть следующую итерацию
            try:
                return max(1, min(5, int(row.get(key, "") or default)))
            except ValueError:
                return default
        parsed.append({
            "debt_id": did, "dtype": dtype, "title": title,
            "description": row.get("Описание", ""),
            "cause": row.get("Причина возникновения", ""),
            "target_state": row.get("Целевое состояние", ""),
            "consequences": row.get("Последствия", ""),
            "risk": risk, "probability": _num("Вероятность"),
            "damage": _num("Ущерб"), "owner": row.get("Владелец") or None,
            "priority": prio, "status": status,
            "repayment_plan": row.get("План погашения", ""),
            "dependencies": row.get("Зависимости", ""),
        })
    return parsed


def import_debts(parsed, user):
    """Upsert: существующий debt_id → обновление; новый → вставка. ID не переиспользуется."""
    created, updated = [], []
    for d in parsed:
        existing = q1("SELECT id FROM tech_debts WHERE debt_id=?", (d["debt_id"],))
        fields = ("dtype", "title", "description", "cause", "target_state", "consequences",
                  "risk", "probability", "damage", "owner", "priority", "status",
                  "repayment_plan", "dependencies")
        if existing:
            sets, args = [], []
            for f in fields:
                sets.append(f"{f}=?"); args.append(d[f])
            exec(f"UPDATE tech_debts SET {', '.join(sets)}, updated_at=? WHERE id=?",
                 (*args, now(), existing["id"]))
            updated.append(d["debt_id"])
        else:
            exec(f"INSERT INTO tech_debts(debt_id,{','.join(fields)},created_by,created_at,updated_at)"
                 f" VALUES(?,{','.join('?' * len(fields))},?,?,?)",
                 (d["debt_id"], *[d[f] for f in fields], user["username"], now(), now()))
            created.append(d["debt_id"])
    return {"created": created, "updated": updated}
