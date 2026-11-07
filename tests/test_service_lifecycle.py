"""Жизненный цикл сервиса: архивирование (lifecycle=decommissioned) и жёсткое удаление.

Архив — обратимый, admin/domain_expert, сервис скрыт из активных срезов (реестр, дашборд).
Удаление — только admin, подтверждение кодом сервиса, блок при in_review,
транзакция с зачисткой дочерних таблиц, запись в audit.
"""

from app.db import q1


def _make_service(client, auth, code):
    r = client.post("/api/services", headers=auth["admin"],
                    json={"code": code, "name": f"Сервис {code}", "project_type": "mvp"})
    assert r.status_code == 200, r.text
    return r.json()


def _in_review(client, auth, sid):
    """Переводит сервис в in_review через реальные API: заполнение → ревью
    (готовность фиксируется автоматически при отправке, ручной self-check упразднён)."""
    A = auth["admin"]
    r = client.patch(f"/api/services/{sid}", headers=A,
                     json={"owner": "a.larshin", "domain": "Payments"})
    assert r.status_code == 200, r.text
    for kind in ["vision_c4", "api", "data_model", "config_build"]:
        r = client.put(f"/api/services/{sid}/artifacts/{kind}", headers=A,
                       json={"content_md": f"# {kind}\nтекст"})
        assert r.status_code == 200, r.text
    r = client.post(f"/api/services/{sid}/reviews", headers=A, json={"comment": "прошу ревью"})
    assert r.status_code == 200, r.text


def test_archive_hides_from_registry_and_dashboard(client, auth):
    A = auth["admin"]
    svc = _make_service(client, auth, "LIFE1")
    sid = svc["id"]

    d0 = client.get("/api/dashboard", headers=A).json()

    # вывод из эксплуатации (админ — разрешено)
    r = client.patch(f"/api/services/{sid}", headers=A, json={"lifecycle": "decommissioned"})
    assert r.status_code == 200, r.text

    # реестр: скрыт по умолчанию, виден с include_archived
    codes = [s["code"] for s in client.get("/api/services", headers=A).json()]
    assert "LIFE1" not in codes
    codes_all = [s["code"] for s in client.get("/api/services?include_archived=1", headers=A).json()]
    assert "LIFE1" in codes_all
    arch = next(s for s in client.get("/api/services?include_archived=1", headers=A).json()
                if s["code"] == "LIFE1")
    assert arch["lifecycle"] == "decommissioned"

    # дашборд: активные срезы без архива, счётчик архивных аддитивен
    d1 = client.get("/api/dashboard", headers=A).json()
    assert d1["total_services"] == d0["total_services"] - 1
    assert d1["archived_services"] == d0["archived_services"] + 1
    assert all(x["id"] != sid for x in d1["readiness"])
    assert all(x["id"] != sid for x in d1["recent"])
    for key in ("no_requirements", "no_c4", "no_checklist"):
        assert all(x["id"] != sid for x in d1["coverage"][key])

    # by_review_status: перевод не попадает ни в одну активную категорию
    assert sum(x["n"] for x in d1["by_review_status"]) == d1["total_services"]

    # возврат в работу — обратимо
    assert client.patch(f"/api/services/{sid}", headers=A,
                        json={"lifecycle": "production"}).status_code == 200
    assert "LIFE1" in [s["code"] for s in client.get("/api/services", headers=A).json()]
    d2 = client.get("/api/dashboard", headers=A).json()
    assert d2["total_services"] == d0["total_services"]
    assert d2["archived_services"] == d0["archived_services"]


def test_delete_permissions_and_confirm(client, auth):
    A, V, E, L = auth["admin"], auth["viewer"], auth["expert"], auth["lead"]
    sid = _make_service(client, auth, "LIFE2")["id"]

    # не-admin — 403 (даже domain_expert и lead)
    for hdr in (V, E, L):
        r = client.request("DELETE", f"/api/services/{sid}", headers=hdr, json={"confirm": "LIFE2"})
        assert r.status_code == 403, (hdr, r.text)

    # admin без confirm / с неверным кодом — 400
    r = client.request("DELETE", f"/api/services/{sid}", headers=A)
    assert r.status_code == 400
    r = client.request("DELETE", f"/api/services/{sid}", headers=A, json={"confirm": "WRONG"})
    assert r.status_code == 400

    # несуществующий сервис — 404
    r = client.request("DELETE", "/api/services/999999", headers=A, json={"confirm": "X"})
    assert r.status_code == 404


def test_delete_blocked_in_review(client, auth):
    A = auth["admin"]
    sid = _make_service(client, auth, "LIFE3")["id"]
    _in_review(client, auth, sid)
    r = client.request("DELETE", f"/api/services/{sid}", headers=A, json={"confirm": "LIFE3"})
    assert r.status_code == 409, r.text
    # сервис остался
    assert client.get(f"/api/services/{sid}", headers=A).status_code == 200


def test_delete_cascades_children_and_audits(client, auth):
    A = auth["admin"]
    svc = _make_service(client, auth, "LIFE4")
    sid = svc["id"]

    # дочерние данные: артефакт, C4-модель, требование
    for kind in ["vision_c4", "api"]:
        assert client.put(f"/api/services/{sid}/artifacts/{kind}", headers=A,
                          json={"content_md": f"# {kind}\nтекст"}).status_code == 200
    assert client.post(f"/api/services/{sid}/requirements", headers=A,
                       json={"type": "FR", "text": "требование"}).status_code == 200

    n_services_before = len(client.get("/api/services?include_archived=1", headers=A).json())

    r = client.request("DELETE", f"/api/services/{sid}", headers=A, json={"confirm": "LIFE4"})
    assert r.status_code == 200, r.text

    # сервис исчез
    assert client.get(f"/api/services/{sid}", headers=A).status_code == 404
    assert len(client.get("/api/services?include_archived=1", headers=A).json()) == n_services_before - 1

    # дочерние таблицы зачищены
    assert q1("SELECT COUNT(*) AS n FROM artifacts WHERE service_id=?", (sid,))["n"] == 0
    assert q1("SELECT COUNT(*) AS n FROM c4_models WHERE service_id=?", (sid,))["n"] == 0
    assert q1("SELECT COUNT(*) AS n FROM requirements WHERE service_id=?", (sid,))["n"] == 0

    # аудит с перечнем удалённого
    row = q1("SELECT action, entity, detail FROM audit_log "
             "WHERE action='service_delete' ORDER BY ts DESC LIMIT 1")
    assert row["action"] == "service_delete"
    assert row["entity"] == "service:LIFE4"
    assert "requirements:1" in row["detail"]
    import re as _re
    m = _re.search(r"artifacts:(\d+)", row["detail"])
    assert m and int(m.group(1)) >= 2          # 9 scaffold-скелетов + 2 заполненных
