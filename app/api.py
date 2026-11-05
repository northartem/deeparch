"""REST API MVP DeepArch (BR-01…13 ядро + BR-14…27 фундамент + RBAC)."""
import json
import secrets
from fastapi import APIRouter, HTTPException, Depends, Body, Header, Response
from .db import q, q1, exec, now
from .auth import current_user, verify_password
from .roles import (GLOBAL_PERMS, has_global, user_groups, group_services,
                    service_scope, can_edit_service, in_committee)
from .standards import (STANDARD_NAME, STANDARD_REF, ARTIFACT_KINDS, CHECKLIST_ITEMS,
                        GRADES, PROJECT_TYPES, REVIEW_STATUSES, LIFECYCLE, ROLES,
                        COMPONENT_KINDS, COMPONENT_STATUSES,
                        DEBT_TYPES, DEBT_STATUSES, DEBT_RISKS, DEBT_PRIORITIES)
from .debts import gen_debt_id
from . import ai, integrations, fitness, factory, nfr, kb, llm
from .seed import seed, demo_vision_template

router = APIRouter(prefix="/api")


def audit(user, action, entity, detail=""):
    exec("INSERT INTO audit_log(ts,user,action,entity,detail) VALUES(?,?,?,?,?)",
         (now(), user["username"], action, entity, detail))


# ---------- стандарт и справочники ----------

@router.get("/standard")
def get_standard(user=Depends(current_user)):
    return {"name": STANDARD_NAME, "ref": STANDARD_REF,
            "artifacts": ARTIFACT_KINDS, "checklist": CHECKLIST_ITEMS,
            "project_types": PROJECT_TYPES, "review_statuses": REVIEW_STATUSES,
            "lifecycle": LIFECYCLE, "component_kinds": COMPONENT_KINDS,
            "component_statuses": COMPONENT_STATUSES,
            "debt_types": DEBT_TYPES, "debt_statuses": DEBT_STATUSES,
            "debt_risks": DEBT_RISKS, "debt_priorities": DEBT_PRIORITIES}


# ---------- аутентификация ----------

@router.post("/login")
def login(body=Body(...)):
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    user = q1("SELECT * FROM users WHERE username=?", (username,))
    if not user or not verify_password(password, user["password_hash"]):
        raise HTTPException(401, "Неверный логин или пароль")
    token = secrets.token_hex(16)
    exec("INSERT INTO sessions(token, username, created_at) VALUES(?,?,?)", (token, username, now()))
    exec("DELETE FROM sessions WHERE username=? AND created_at < ?",
         (username, now() - 7 * 24 * 3600))  # сессии старше 7 дней
    return {"token": token, "user": {k: user[k] for k in ("username", "display_name", "role")}}


@router.post("/logout")
def logout(user=Depends(current_user), x_token: str = Header(default=None)):
    exec("DELETE FROM sessions WHERE token=?", (x_token,))
    return {"ok": True}


@router.get("/me")
def me(user=Depends(current_user)):
    return {k: user[k] for k in ("username", "display_name", "role")}


# ---------- реестр сервисов (BR-01) + скоуп-доступ ----------

@router.get("/services")
def list_services(user=Depends(current_user)):
    rows = q("""SELECT s.*,
                (SELECT MAX(score_pct) FROM checklist_runs c WHERE c.service_id=s.id) AS last_score
                FROM services s ORDER BY s.name""")
    for r in rows:
        r["mandatory_artifacts"] = _mandatory_kinds(r["project_type"])
    return rows


@router.post("/services")
def create_service(body=Body(...), user=Depends(current_user)):
    if user["role"] not in ("admin", "domain_expert", "team_lead"):
        raise HTTPException(403, "Создание сервисов: team_lead, domain_expert, admin")
    code = (body.get("code") or "").strip().upper()
    if not code or not body.get("name"):
        raise HTTPException(400, "Нужны code и name")
    if q1("SELECT id FROM services WHERE code=?", (code,)):
        raise HTTPException(409, f"Сервис с кодом {code} уже есть")
    pt = body.get("project_type") or "mvp"
    if pt not in PROJECT_TYPES:
        raise HTTPException(400, f"project_type должен быть из: {', '.join(PROJECT_TYPES)}")
    # создатель по умолчанию становится владельцем → сразу получает скоуп team
    owner = body.get("owner") or user["username"]
    sid = exec("INSERT INTO services(code,name,domain,owner,architect,project_type,lifecycle,review_status,created_at,updated_at)"
               " VALUES(?,?,?,?,?,?,?,?,?,?)",
               (code, body["name"], body.get("domain"), owner, body.get("architect"),
                pt, body.get("lifecycle") or "design", "draft", now(), now()))
    for a in ARTIFACT_KINDS:
        exec("INSERT INTO artifacts(service_id,kind,content_md,version,updated_by,updated_at) VALUES(?,?,?,?,?,?)",
             (sid, a["kind"], "", 1, user["username"], now()))
    exec("INSERT INTO checklist_runs(service_id,answers,score_pct,mandatory_missing,created_by,created_at) VALUES(?,?,?,?,?,?)",
         (sid, json.dumps([]), 0.0, 0, user["username"], now()))
    audit(user, "create_service", f"service:{code}", body["name"])
    return {"id": sid, "code": code}


def _mandatory_kinds(project_type):
    pt = PROJECT_TYPES.get(project_type, {})
    return [k for k, v in pt.get("matrix", {}).items() if v == "mandatory"]


@router.get("/services/{sid}")
def get_service(sid: int, user=Depends(current_user)):
    svc = q1("SELECT * FROM services WHERE id=?", (sid,))
    if not svc:
        raise HTTPException(404, "Сервис не найден")
    svc["my_scope"] = service_scope(user, svc)   # full / team / none — для UI
    svc["mandatory_artifacts"] = _mandatory_kinds(svc["project_type"])
    svc["debts"] = [dict(r, ds=r["probability"] * r["damage"]) for r in
                    q("SELECT * FROM tech_debts WHERE service_id=? ORDER BY id DESC", (sid,))]
    svc["artifacts"] = q("SELECT * FROM artifacts WHERE service_id=? ORDER BY kind", (sid,))
    svc["checklist_runs"] = q("SELECT id,score_pct,mandatory_missing,created_by,created_at FROM checklist_runs"
                              " WHERE service_id=? ORDER BY created_at DESC LIMIT 10", (sid,))
    svc["reviews"] = q("SELECT * FROM reviews WHERE service_id=? ORDER BY requested_at DESC", (sid,))
    svc["components"] = q("""SELECT c.* FROM components c JOIN service_components sc ON sc.component_id=c.id
                              WHERE sc.service_id=?""", (sid,))
    last = q1("SELECT answers FROM checklist_runs WHERE service_id=? ORDER BY created_at DESC LIMIT 1", (sid,))
    svc["last_answers"] = json.loads(last["answers"]) if last and last["answers"] else []
    svc["nfr"] = nfr.validate(sid)                       # MVP2 BR-51…53
    run = q1("SELECT id,passed,failed,warned,created_by,created_at FROM fitness_runs"
             " WHERE service_id=? ORDER BY created_at DESC LIMIT 1", (sid,))
    svc["fitness_last"] = dict(run) if run else None     # MVP2 BR-42
    return svc


@router.patch("/services/{sid}")
def update_service(sid: int, body=Body(...), user=Depends(current_user)):
    svc = q1("SELECT * FROM services WHERE id=?", (sid,))
    if not svc:
        raise HTTPException(404, "Сервис не найден")
    if not can_edit_service(user, svc):
        raise HTTPException(403, "Нет прав на этот сервис: доступ дают product-группа или роль owner/architect")
    fields = ["name", "domain", "owner", "architect", "project_type", "lifecycle", "cmdb_id"]
    sets, params = [], []
    for f in fields:
        if f in body:
            if f == "project_type" and body[f] not in PROJECT_TYPES:
                raise HTTPException(400, "Неизвестный project_type")
            sets.append(f"{f}=?"); params.append(body[f])
    if sets:
        params += [now(), sid]
        exec(f"UPDATE services SET {', '.join(sets)}, updated_at=? WHERE id=?", params)
        audit(user, "update_service", f"service:{svc['code']}", ", ".join(sets))
    return {"ok": True}


# ---------- артефакты (BR-02) ----------

@router.put("/services/{sid}/artifacts/{kind}")
def save_artifact(sid: int, kind: str, body=Body(...), user=Depends(current_user)):
    if kind not in {a["kind"] for a in ARTIFACT_KINDS}:
        raise HTTPException(400, "Неизвестный вид артефакта")
    a = q1("SELECT * FROM artifacts WHERE service_id=? AND kind=?", (sid, kind))
    if not a:
        raise HTTPException(404, "Артефакт не найден")
    svc = q1("SELECT * FROM services WHERE id=?", (sid,))
    if not can_edit_service(user, svc):
        raise HTTPException(403, "Нет прав на этот сервис: доступ дают product-группа или роль owner/architect")
    exec("UPDATE artifacts SET content_md=?, source_url=?, diagram_code=?, version=version+1, updated_by=?, updated_at=? WHERE id=?",
         (body.get("content_md", a["content_md"]), body.get("source_url", a["source_url"]),
          body.get("diagram_code", a["diagram_code"]),
          user["username"], now(), a["id"]))
    exec("UPDATE services SET updated_at=? WHERE id=?", (now(), sid))
    audit(user, "save_artifact", f"service:{sid}/{kind}", f"v{a['version']+1}")
    return {"ok": True, "version": a["version"] + 1}


# ---------- self-check (BR-03) ----------

@router.post("/services/{sid}/checklist")
def run_checklist(sid: int, body=Body(...), user=Depends(current_user)):
    svc = q1("SELECT * FROM services WHERE id=?", (sid,))
    if not svc:
        raise HTTPException(404, "Сервис не найден")
    if not can_edit_service(user, svc):
        raise HTTPException(403, "Нет прав на этот сервис")
    answers_in = {int(a["item_id"]): a for a in body.get("answers", [])}
    answers, score, mandatory_missing = [], 0.0, 0
    for it in CHECKLIST_ITEMS:
        ans = answers_in.get(it["id"], {})
        grade = ans.get("grade", "N")
        if grade not in GRADES:
            raise HTTPException(400, f"Оценка должна быть E/Ch/N (пункт {it['id']})")
        link = (ans.get("link") or "").strip()
        # Правило стандарта: «Пункт без ссылки не считается пройденным»
        if grade != "N" and not link:
            grade = "Ch"
        answers.append({"item_id": it["id"], "grade": grade, "link": link})
        score += GRADES[grade]
        if it["weight"] == "mandatory" and grade != "E":
            mandatory_missing += 1
    score_pct = round(100.0 * score / len(CHECKLIST_ITEMS), 1)
    rid = exec("INSERT INTO checklist_runs(service_id,answers,score_pct,mandatory_missing,created_by,created_at) VALUES(?,?,?,?,?,?)",
               (sid, json.dumps(answers), score_pct, mandatory_missing, user["username"], now()))
    audit(user, "self_check", f"service:{svc['code']}", f"score={score_pct}% blockers={mandatory_missing}")
    blocking = [a for a in answers if a["grade"] != "E" and
                next(i for i in CHECKLIST_ITEMS if i["id"] == a["item_id"])["weight"] == "mandatory"]
    return {"run_id": rid, "score_pct": score_pct, "mandatory_missing": mandatory_missing,
            "blocking_items": [b["item_id"] for b in blocking],
            "verdict": "ready_for_review" if mandatory_missing == 0 else "not_ready"}


# ---------- ревью (BR-04/BR-05) ----------

@router.post("/services/{sid}/reviews")
def request_review(sid: int, body=Body(...), user=Depends(current_user)):
    svc = q1("SELECT * FROM services WHERE id=?", (sid,))
    if not svc:
        raise HTTPException(404, "Сервис не найден")
    if not can_edit_service(user, svc):
        raise HTTPException(403, "Нет прав на этот сервис")
    if svc["review_status"] == "in_review":
        raise HTTPException(409, "Ревью уже идёт")
    last = q1("SELECT * FROM checklist_runs WHERE service_id=? ORDER BY created_at DESC LIMIT 1", (sid,))
    has_answers = last and len(json.loads(last["answers"])) > 0
    if not has_answers or last["mandatory_missing"] > 0:
        raise HTTPException(409, "Self-check не пройден: есть незакрытые обязательные пункты. Сначала закройте чек-лист.")
    rid = exec("INSERT INTO reviews(service_id,requested_by,requested_at,status,comment) VALUES(?,?,?,?,?)",
               (sid, user["username"], now(), "in_review", body.get("comment")))
    exec("UPDATE services SET review_status='in_review', updated_at=? WHERE id=?", (now(), sid))
    audit(user, "request_review", f"service:{svc['code']}", f"review#{rid}")
    return {"review_id": rid, "status": "in_review"}


@router.post("/reviews/{rid}/decision")
def decide_review(rid: int, body=Body(...), user=Depends(current_user)):
    # решение: domain_expert/admin ИЛИ член Архитектурного комитета
    if not (has_global(user, "review.decide") or in_committee(user["username"])):
        raise HTTPException(403, "Решение по ревью: domain_expert, admin или Архитектурный комитет")
    rv = q1("SELECT * FROM reviews WHERE id=?", (rid,))
    if not rv:
        raise HTTPException(404, "Ревью не найдено")
    if rv["status"] != "in_review":
        raise HTTPException(409, "Ревью уже закрыто")
    verdict = body.get("verdict")
    if verdict not in ("approved", "changes_requested"):
        raise HTTPException(400, "verdict: approved | changes_requested")
    exec("UPDATE reviews SET status=?, reviewer=?, comment=?, decided_at=? WHERE id=?",
         (verdict, user["username"], body.get("comment"), now(), rid))
    exec("UPDATE services SET review_status=?, updated_at=? WHERE id=?", (verdict, now(), rv["service_id"]))
    svc = q1("SELECT code FROM services WHERE id=?", (rv["service_id"],))
    audit(user, "review_decision", f"service:{svc['code']}", f"review#{rid} → {verdict}")
    return {"ok": True, "verdict": verdict}


# ---------- каталог переиспользуемых компонентов (BR-14…19) ----------

@router.get("/components")
def list_components(user=Depends(current_user)):
    rows = q("SELECT c.*, (SELECT COUNT(*) FROM service_components sc WHERE sc.component_id=c.id) AS used_by"
             " FROM components c ORDER BY c.name")
    return rows


@router.post("/components")
def create_component(body=Body(...), user=Depends(current_user)):
    if not has_global(user, "component.manage"):
        raise HTTPException(403, "Каталогом управляют domain_expert/admin; team_lead может предложить компонент через эксперта")
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Нужно name")
    if q1("SELECT id FROM components WHERE name=?", (name,)):
        raise HTTPException(409, "Компонент с таким именем уже есть")
    cid = exec("INSERT INTO components(name,kind,description,status,owner_team,standard_ref,adr_ref,repo_url,created_at)"
               " VALUES(?,?,?,?,?,?,?,?,?)",
               (name, body.get("kind") or "pattern", body.get("description", ""),
                body.get("status") or "proposed", body.get("owner_team"), body.get("standard_ref"),
                body.get("adr_ref"), body.get("repo_url"), now()))
    audit(user, "create_component", f"component:{name}")
    return {"id": cid}


@router.post("/services/{sid}/components")
def attach_component(sid: int, body=Body(...), user=Depends(current_user)):
    svc = q1("SELECT * FROM services WHERE id=?", (sid,))
    if not svc:
        raise HTTPException(404, "Сервис не найден")
    if not can_edit_service(user, svc):
        raise HTTPException(403, "Нет прав на этот сервис")
    comp = q1("SELECT * FROM components WHERE id=?", (body.get("component_id"),))
    if not comp:
        raise HTTPException(404, "Компонент не найден")
    if q1("SELECT * FROM service_components WHERE service_id=? AND component_id=?", (sid, comp["id"])):
        return {"ok": True, "note": "уже подключён"}
    exec("INSERT INTO service_components(service_id, component_id) VALUES(?,?)", (sid, comp["id"]))
    audit(user, "attach_component", f"service:{sid}", comp["name"])
    return {"ok": True, "status": comp["status"],
            "note": "approved-компонент закрывает связанные пункты стандарта (compliance by construction)"
            if comp["status"] == "approved" else None}


# ---------- AI (BR-27…37) ----------

@router.post("/ai/draft")
def ai_draft(body=Body(...), user=Depends(current_user)):
    svc = q1("SELECT * FROM services WHERE id=?", (body.get("service_id"),))
    if not svc:
        raise HTTPException(404, "Сервис не найден")
    if not can_edit_service(user, svc):
        raise HTTPException(403, "Нет прав на этот сервис")
    r = ai.draft_artifact(body.get("service_id"), body.get("kind"))
    if not r:
        raise HTTPException(404, "Артефакт не найден")
    audit(user, "ai_draft", f"service:{body.get('service_id')}/{body.get('kind')}", "mock")
    return r


@router.post("/ai/precheck")
def ai_precheck(body=Body(...), user=Depends(current_user)):
    r = ai.predict_checklist(body.get("service_id"))
    if not r:
        raise HTTPException(404, "Сервис не найден")
    audit(user, "ai_precheck", f"service:{body.get('service_id')}", "mock")
    return r


# ---------- интеграции с каталогом/CMDB (BR-20…23) ----------

@router.post("/integrations/backstage/import")
def backstage_import(body=Body(default={}), user=Depends(current_user)):
    if not has_global(user, "integration.import"):
        raise HTTPException(403, "Импорт доступен domain_expert/admin")
    res = integrations.import_from_backstage(dry_run=bool(body.get("dry_run", True)))
    audit(user, "backstage_import", "integrations", f"created={len(res['created'])}")
    return res


@router.get("/integrations/services/{sid}/catalog-export")
def catalog_export(sid: int, user=Depends(current_user)):
    r = integrations.sync_to_catalog(sid)
    if not r:
        raise HTTPException(404, "Сервис не найден")
    return r


# ---------- дашборд и аудит ----------

@router.get("/dashboard")
def dashboard(user=Depends(current_user)):
    total = q1("SELECT COUNT(*) AS n FROM services")["n"]
    by_status = q("SELECT review_status, COUNT(*) AS n FROM services GROUP BY review_status")
    latest = q("""SELECT s.id, s.code, s.name, s.review_status,
                  (SELECT score_pct FROM checklist_runs c WHERE c.service_id=s.id ORDER BY created_at DESC LIMIT 1) AS score
                  FROM services s ORDER BY s.updated_at DESC LIMIT 8""")
    comp_usage = q("""SELECT c.name, c.status, COUNT(sc.service_id) AS used_by
                       FROM components c LEFT JOIN service_components sc ON sc.component_id=c.id
                       GROUP BY c.id ORDER BY used_by DESC""")
    return {"total_services": total, "by_review_status": by_status, "recent": latest,
            "component_usage": comp_usage,
            "standard_ref": STANDARD_REF}


@router.get("/audit")
def get_audit(user=Depends(current_user)):
    if not (has_global(user, "audit.view") or user["role"] == "admin"):
        raise HTTPException(403, "Журнал аудита: admin, domain_expert, InfoSec")
    return q("SELECT * FROM audit_log ORDER BY ts DESC LIMIT 100")


@router.post("/admin/seed")
def reseed(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Только admin")
    seed()
    return {"ok": True}


# ---------- технический долг (BR-38…40) ----------

@router.get("/debts")
def list_debts(dtype: str = None, service_id: int = None, status: str = None,
               priority: str = None, user=Depends(current_user)):
    sql, args = "SELECT d.*, s.code AS service_code, s.name AS service_name FROM tech_debts d" \
                " LEFT JOIN services s ON s.id = d.service_id WHERE 1=1", []
    if dtype:
        sql += " AND d.dtype=?"; args.append(dtype)
    if service_id:
        sql += " AND d.service_id=?"; args.append(service_id)
    if status:
        sql += " AND d.status=?"; args.append(status)
    if priority:
        sql += " AND d.priority=?"; args.append(priority)
    sql += " ORDER BY CASE d.priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END," \
           " d.probability * d.damage DESC"
    return [dict(r, ds=r["probability"] * r["damage"]) for r in q(sql, tuple(args))]


@router.post("/debts")
def create_debt(body=Body(...), user=Depends(current_user)):
    svc = q1("SELECT * FROM services WHERE id=?", (body.get("service_id"),))
    if svc:
        if not can_edit_service(user, svc):
            raise HTTPException(403, "Нет прав на этот сервис")
    elif user["role"] not in ("admin", "domain_expert"):
        raise HTTPException(403, "Долг без привязки к сервису регистрируют domain_expert/admin")
    dtype = body.get("dtype")
    if dtype not in ("AD", "TD"):
        raise HTTPException(400, "dtype: AD (архитектурный) | TD (технический)")
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "Нужно title — краткое описание долга")
    ts = now()
    debt_id = gen_debt_id(dtype, ts)   # ID присваивается один раз и неизменяем
    fields = ("dtype", "service_id", "title", "description", "cause", "arch_decision",
              "target_state", "consequences", "business_impact", "tech_impact", "risk",
              "probability", "damage", "maintenance_cost", "repayment_cost", "owner",
              "priority", "status", "review_date", "repayment_plan", "dependencies")
    vals = [body.get(f) for f in fields]
    vals[10] = vals[10] if vals[10] in DEBT_RISKS else "Medium"
    vals[11] = max(1, min(5, int(vals[11] or 3)))   # вероятность 1–5
    vals[12] = max(1, min(5, int(vals[12] or 3)))   # ущерб 1–5
    vals[17] = vals[17] if vals[17] in DEBT_STATUSES else "new"
    vals[18] = vals[18] if vals[18] in DEBT_PRIORITIES else "P2"
    did = exec(f"INSERT INTO tech_debts(debt_id,{','.join(fields)},created_by,created_at,updated_at)"
               f" VALUES(?,{','.join('?' * len(fields))},?,?,?)",
               (debt_id, *vals, user["username"], ts, ts))
    audit(user, "debt_register", f"debt:{debt_id}", title[:80])
    return {"id": did, "debt_id": debt_id, "ds": vals[11] * vals[12]}


@router.patch("/debts/{did}")
def update_debt(did: int, body=Body(...), user=Depends(current_user)):
    d = q1("SELECT * FROM tech_debts WHERE id=?", (did,))
    if not d:
        raise HTTPException(404, "Запись не найдена")
    svc = q1("SELECT * FROM services WHERE id=?", (d["service_id"],)) if d["service_id"] else None
    can_edit = (svc and can_edit_service(user, svc)) or \
               d["owner"] == user["username"] or has_global(user, "review.decide")
    if not can_edit:
        raise HTTPException(403, "Редактирование: владелец записи, редактор сервиса, domain_expert/admin")
    for f in ("title", "description", "cause", "arch_decision", "target_state", "consequences",
              "business_impact", "tech_impact", "risk", "probability", "damage",
              "maintenance_cost", "repayment_cost", "owner", "priority",
              "review_date", "repayment_plan", "dependencies"):
        if f in body:
            exec(f"UPDATE tech_debts SET {f}=? WHERE id=?", (body[f], did))
    if body.get("risk") and body["risk"] not in DEBT_RISKS:
        raise HTTPException(400, f"risk: {'|'.join(DEBT_RISKS)}")
    exec("UPDATE tech_debts SET updated_at=? WHERE id=?", (now(), did))
    audit(user, "debt_update", f"debt:{d['debt_id']}", ",".join(body.keys()))
    return {"ok": True}


@router.post("/debts/{did}/status")
def change_debt_status(did: int, body=Body(...), user=Depends(current_user)):
    d = q1("SELECT * FROM tech_debts WHERE id=?", (did,))
    if not d:
        raise HTTPException(404, "Запись не найдена")
    status = body.get("status")
    if status not in DEBT_STATUSES:
        raise HTTPException(400, f"status: {'|'.join(DEBT_STATUSES)}")
    svc = q1("SELECT * FROM services WHERE id=?", (d["service_id"],)) if d["service_id"] else None
    # AD — решения уровня архитектуры: domain_expert/admin; TD — команда сервиса тоже
    allowed = has_global(user, "review.decide") or d["owner"] == user["username"]
    if not allowed and (d["dtype"] == "TD" and svc and can_edit_service(user, svc)):
        allowed = True
    if not allowed:
        raise HTTPException(403, "Смена статуса: domain_expert/admin, владелец записи"
                                 + (", редактор сервиса (для TD)" if d["dtype"] == "TD" else ""))
    old = d["status"]
    exec("UPDATE tech_debts SET status=?, updated_at=? WHERE id=?", (status, now(), did))
    audit(user, "debt_status", f"debt:{d['debt_id']}", f"{old} → {status}")
    return {"ok": True, "status": status}


# ---------- ролевая модель: управление доступом ----------

KINDS = ("domain", "committee", "product", "security")


def _require_admin(user):
    if user["role"] != "admin":
        raise HTTPException(403, "Управление доступом — только admin")


@router.get("/admin/access")
def access_overview(user=Depends(current_user)):
    if user["role"] not in ("admin", "domain_expert"):
        raise HTTPException(403, "Обзор доступа: admin, domain_expert")
    users = []
    for u in q("SELECT username, display_name, role FROM users ORDER BY role, username"):
        u["groups"] = [g["name"] for g in user_groups(u["username"])]
        users.append(u)
    groups = []
    for g in q("SELECT * FROM groups ORDER BY kind, name"):
        g["members"] = [r["username"] for r in
                        q("SELECT username FROM group_members WHERE group_id=? ORDER BY username", (g["id"],))]
        g["services"] = q("""SELECT s.id, s.code, s.name FROM service_grants sg
                             JOIN services s ON s.id = sg.service_id
                             WHERE sg.group_id=? ORDER BY s.code""", (g["id"],))
        groups.append(g)
    return {"users": users, "groups": groups, "roles": ROLES, "kinds": KINDS}


@router.post("/admin/groups")
def create_group(body=Body(...), user=Depends(current_user)):
    _require_admin(user)
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Нужно name")
    if q1("SELECT id FROM groups WHERE name=?", (name,)):
        raise HTTPException(409, "Группа уже есть")
    kind = body.get("kind") or "product"
    if kind not in KINDS:
        raise HTTPException(400, f"kind: {'|'.join(KINDS)}")
    gid = exec("INSERT INTO groups(name, kind, description) VALUES(?,?,?)",
               (name, kind, body.get("description", "")))
    audit(user, "create_group", f"group:{name}", kind)
    return {"id": gid}


@router.post("/admin/groups/{gid}/members")
def add_member(gid: int, body=Body(...), user=Depends(current_user)):
    _require_admin(user)
    if not q1("SELECT id FROM groups WHERE id=?", (gid,)):
        raise HTTPException(404, "Группа не найдена")
    if not q1("SELECT id FROM users WHERE username=?", (body.get("username"),)):
        raise HTTPException(404, "Пользователь не найден")
    exec("INSERT OR IGNORE INTO group_members(group_id, username) VALUES(?,?)", (gid, body["username"]))
    audit(user, "group_add_member", f"group:{gid}", body["username"])
    return {"ok": True}


@router.post("/admin/groups/{gid}/members/remove")
def remove_member(gid: int, body=Body(...), user=Depends(current_user)):
    _require_admin(user)
    exec("DELETE FROM group_members WHERE group_id=? AND username=?", (gid, body.get("username")))
    audit(user, "group_remove_member", f"group:{gid}", body.get("username"))
    return {"ok": True}


@router.post("/admin/groups/{gid}/services")
def grant_service(gid: int, body=Body(...), user=Depends(current_user)):
    _require_admin(user)
    if not q1("SELECT id FROM groups WHERE id=?", (gid,)):
        raise HTTPException(404, "Группа не найдена")
    if not q1("SELECT id FROM services WHERE id=?", (body.get("service_id"),)):
        raise HTTPException(404, "Сервис не найден")
    exec("INSERT OR IGNORE INTO service_grants(group_id, service_id) VALUES(?,?)", (gid, body["service_id"]))
    audit(user, "group_grant_service", f"group:{gid}", str(body.get("service_id")))
    return {"ok": True}


@router.post("/admin/groups/{gid}/services/remove")
def revoke_service(gid: int, body=Body(...), user=Depends(current_user)):
    _require_admin(user)
    exec("DELETE FROM service_grants WHERE group_id=? AND service_id=?", (gid, body.get("service_id")))
    audit(user, "group_revoke_service", f"group:{gid}", str(body.get("service_id")))
    return {"ok": True}


@router.patch("/admin/users/{username}/role")
def set_role(username: str, body=Body(...), user=Depends(current_user)):
    _require_admin(user)
    u = q1("SELECT * FROM users WHERE username=?", (username,))
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    role = body.get("role")
    if role not in ROLES:
        raise HTTPException(400, f"Роль должна быть из: {', '.join(ROLES)}")
    exec("UPDATE users SET role=? WHERE username=?", (role, username))
    audit(user, "set_role", f"user:{username}", f"{u['role']} → {role}")
    return {"ok": True, "role": role}


# ---------- MVP2: fitness functions (BR-41…44) ----------

@router.get("/fitness/rules")
def fitness_rules(user=Depends(current_user)):
    return [dict(r) for r in q("SELECT * FROM fitness_rules WHERE active=1 ORDER BY id")]


@router.post("/services/{sid}/fitness")
def run_fitness(sid: int, user=Depends(current_user)):
    svc = q1("SELECT * FROM services WHERE id=?", (sid,))
    if not svc:
        raise HTTPException(404, "Сервис не найден")
    result = fitness.run_fitness(svc, user)
    audit(user, "fitness_run", f"service:{svc['code']}",
          f"pass:{result['passed']} fail:{result['failed']} warn:{result['warned']}")
    return result


@router.get("/services/{sid}/fitness/ci.txt")
def fitness_ci(sid: int, user=Depends(current_user)):
    svc = q1("SELECT * FROM services WHERE id=?", (sid,))
    if not svc:
        raise HTTPException(404, "Сервис не найден")
    yaml, python = fitness.ci_pack(svc)
    pack = (f"# gitlab-ci (скопируйте в .gitlab-ci.yml)\n{yaml}\n"
            "# fitness/<code>_check.py (автономный скрипт)\n" + python)
    return Response(pack, media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition":
                             f'attachment; filename="fitness_{svc["code"].lower()}.txt"'})


# ---------- MVP2: Service Factory (BR-45…47) ----------

@router.post("/factory/scaffold")
def factory_scaffold(body=Body(...), user=Depends(current_user)):
    if user["role"] not in ("admin", "domain_expert", "team_lead"):
        raise HTTPException(403, "Скаффолдинг: team_lead, domain_expert, admin")
    code = (body.get("code") or "").strip().upper()
    if not code or not body.get("name"):
        raise HTTPException(400, "Нужны code и name")
    try:
        r = factory.scaffold(code, body["name"].strip(), body.get("domain"),
                             body.get("project_type") or "mvp",
                             body.get("owner") or user["username"],
                             body.get("architect"), user["username"],
                             body.get("lifecycle") or "design")
    except ValueError as e:
        raise HTTPException(409, str(e))
    audit(user, "factory_scaffold", f"service:{code}",
          f"artifacts:{r['artifacts']} components:{len(r['components_attached'])}")
    return r


# ---------- MVP2: RAG-ассистент (BR-48…50) ----------

@router.post("/assistant")
def assistant(body=Body(...), user=Depends(current_user)):
    question = (body.get("question") or "").strip()
    if not question:
        raise HTTPException(400, "Нужен question")
    r = kb.answer(question)
    r["mode"] = "advisory"   # BR-33: решение за человеком
    return r


@router.get("/assistant/status")
def assistant_status(user=Depends(current_user)):
    return kb.status()


# ---------- MVP2: подключение LLM в админ-панели ----------

@router.get("/admin/llm")
def llm_config(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Настройки LLM — только admin")
    url, _, model = llm.config()
    return {"configured": llm.configured(), "source": llm.source(),
            "url": url or "", "model": model,
            "token_set": bool(llm.config()[1]), "token_masked": llm.masked_token()}


@router.post("/admin/llm")
def llm_save(body=Body(...), user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Настройки LLM — только admin")
    url = (body.get("url") or "").strip()
    if url and not url.startswith(("http://", "https://")):
        raise HTTPException(400, "URL должен начинаться с http:// или https://")
    llm.save_settings(url, body.get("token") or "", body.get("model") or "")
    audit(user, "llm_config", "llm", f"url={url or '—'} (источник: settings)")
    return llm_config(user)   # конфигурация без env могла не примениться — вернём факт


@router.post("/admin/llm/test")
def llm_test(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Настройки LLM — только admin")
    r = llm.test_connection()
    audit(user, "llm_test", "llm", f"ok={r['ok']} {r['latency_ms']}ms")
    return r


@router.post("/admin/llm/remove")
def llm_remove(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Настройки LLM — только admin")
    llm.clear_settings()
    audit(user, "llm_config", "llm", "отключена (настройки удалены)")
    return {"ok": True}


# ---------- MVP2: NFR-валидация (BR-51…53) ----------

@router.post("/services/{sid}/nfr/extract")
def nfr_extract(sid: int, user=Depends(current_user)):
    svc = q1("SELECT * FROM services WHERE id=?", (sid,))
    if not svc:
        raise HTTPException(404, "Сервис не найден")
    ex = nfr.extract_targets(sid)
    saved = nfr.apply_targets(sid, user, ex["extracted"]) if ex["extracted"] else []
    return {**ex, "saved": saved}


@router.patch("/nfr/{mid}")
def nfr_update(mid: int, body=Body(...), user=Depends(current_user)):
    m = q1("SELECT * FROM nfr_metrics WHERE id=?", (mid,))
    if not m:
        raise HTTPException(404, "Метрика не найдена")
    svc = q1("SELECT * FROM services WHERE id=?", (m["service_id"],))
    if not can_edit_service(user, svc):
        raise HTTPException(403, "Нет прав на этот сервис")
    for f in ("target_value", "actual_value", "target_note", "source"):
        if f in body:
            exec(f"UPDATE nfr_metrics SET {f}=? WHERE id=?", (body[f], mid))
    if "actual_value" in body:
        exec("UPDATE nfr_metrics SET measured_at=? WHERE id=?", (now(), mid))
    audit(user, "nfr_update", f"service:{svc['code']}", f"{m['metric']}: {', '.join(body.keys())}")
    return nfr.validate(m["service_id"])


# ---------- MVP2: синхронизация с Confluence (BR-54…56) ----------

@router.post("/integrations/confluence/export")
def confluence_export(body=Body(default={}), user=Depends(current_user)):
    r = integrations.export_debts_xhtml(body.get("service_id"))
    audit(user, "confluence_export", f"page:{integrations.DEBT_PAGE_ID}",
          f"records:{r['records']}")
    return r


@router.post("/integrations/confluence/import")
def confluence_import(body=Body(...), user=Depends(current_user)):
    if user["role"] not in ("admin", "domain_expert"):
        raise HTTPException(403, "Импорт реестра: domain_expert, admin")
    parsed = integrations.parse_debts_markdown(body.get("markdown") or "")
    if not parsed:
        raise HTTPException(400, "В тексте не найдено записей реестра (markdown-таблица с колонкой ID)")
    r = integrations.import_debts(parsed, user)
    audit(user, "confluence_import", f"page:{integrations.DEBT_PAGE_ID}",
          f"created:{len(r['created'])} updated:{len(r['updated'])}")
    return r
