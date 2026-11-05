"""
Интеграционный слой с каталогом/CMDB (BR-20…BR-23).

Абстракция CatalogAdapter: пока реализован MockBackstageAdapter.
В проде — модуль @backstage/plugin-catalog-backend-module-gitlab читает
catalog-info.yaml из GitLab; DataGerry — через REST API (pageId=915904198).
"""
from .db import exec, q1, q, now
from .seed import demo_vision_template

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
    import json
    return {"service_id": service_id, "catalog_entity": payload, "generated": "catalog-info.yaml (mock)"}
