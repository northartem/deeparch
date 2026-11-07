"""REST API MVP DeepArch (BR-01…13 ядро + BR-14…27 фундамент + RBAC)."""
import json
import re
import secrets

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Response
from fastapi.responses import StreamingResponse

from . import ai, ai_review, factory, fitness, integrations, kb, llm, nfr, reqs
from . import c4 as c4mod
from .auth import current_user, verify_password
from .db import exec, get_conn, now, q, q1
from .debts import gen_debt_id
from .roles import can_edit_service, has_global, in_committee, service_scope, user_groups
from .seed import seed
from .standards import (
    ARTIFACT_KINDS,
    CHECKLIST_ITEMS,
    COMPONENT_KINDS,
    COMPONENT_STATUSES,
    DEBT_PRIORITIES,
    DEBT_RISKS,
    DEBT_STATUSES,
    DEBT_TYPES,
    GRADES,
    LIFECYCLE,
    PROJECT_TYPES,
    REVIEW_STATUSES,
    ROLES,
    STANDARD_NAME,
    STANDARD_REF,
)

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
def list_services(include_archived: int = None, user=Depends(current_user)):
    """По умолчанию архив (lifecycle='decommissioned') скрыт; include_archived=1 показывает его."""
    rows = q(f"""SELECT s.*,
                (SELECT MAX(score_pct) FROM checklist_runs c WHERE c.service_id=s.id) AS last_score
                FROM services s {'' if include_archived else "WHERE s.lifecycle != 'decommissioned'"} ORDER BY s.name""")
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


def _auto_checklist(svc) -> list[dict]:
    """Готовность к ревью вычисляется из данных DeepArch (принцип «всё хранится в платформе»):
    пункт = «Есть», если его артефакт заполнен. Ручные оценки Е/Ч/Н упразднены —
    человеческое суждение остаётся у ревьюера, а не в формальной таблице."""
    sid = svc["id"]
    answers = []
    for it in CHECKLIST_ITEMS:
        href = f"#/service/{sid}/artifacts" if it["artifact"] else f"#/service/{sid}/card"
        if it["artifact"] is None:                       # пункт 10 — карточка сервиса
            filled = bool(svc["name"] and (svc["owner"] or "").strip() and (svc["domain"] or "").strip())
        else:
            a = q1("SELECT content_md, diagram_code FROM artifacts WHERE service_id=? AND kind=?",
                   (sid, it["artifact"]))
            filled = bool(a and ((a["content_md"] or "").strip() or (a["diagram_code"] or "").strip()))
        answers.append({"item_id": it["id"], "grade": "E" if filled else "N", "link": href})
    return answers


def _auto_blockers(svc, answers) -> list[str]:
    """Блокируют пункты обязательного набора матрицы типа проекта («минимальные
    наборы» стандарта — авторитетный источник gate) и пункт «Карточка сервиса».
    Веса чек-листа остаются в скоринге и истории, но тип проекта точнее отражает
    требования: ADR для mvp — desired, модель данных — mandatory."""
    sid = svc["id"]
    mandatory_kinds = set(_mandatory_kinds(svc["project_type"]))
    by_id = {a["item_id"]: a for a in answers}
    blockers = [it["item"] for it in CHECKLIST_ITEMS
                if by_id[it["id"]]["grade"] != "E"
                and (it["artifact"] is None or it["artifact"] in mandatory_kinds)]
    # виды артефактов, обязательные по матрице, но не покрытые пунктами чек-листа
    # (threat_model, drp_bcp для critical) — проверяем напрямую
    covered = {it["artifact"] for it in CHECKLIST_ITEMS if it["artifact"]}
    for kind in mandatory_kinds - covered:
        a = q1("SELECT content_md, diagram_code FROM artifacts WHERE service_id=? AND kind=?",
               (sid, kind))
        if not (a and ((a["content_md"] or "").strip() or (a["diagram_code"] or "").strip())):
            blockers.append(next((t["title"] for t in ARTIFACT_KINDS if t["kind"] == kind), kind))
    return blockers


def _checklist_score(answers) -> float:
    score = sum(GRADES[a["grade"]] for a in answers)
    return round(100.0 * score / len(CHECKLIST_ITEMS), 1)


def _next_steps(svc) -> list[str]:
    """Живые Next Steps для карточки сервиса: что реально мешает готовности к ревью
    (в отличие от статического списка factory при создании)."""
    arts = {a["kind"]: a for a in
            q("SELECT kind, content_md FROM artifacts WHERE service_id=?", (svc["id"],))}
    steps = []
    missing = [k for k in _mandatory_kinds(svc["project_type"])
               if not (arts.get(k, {}).get("content_md") or "").strip()]
    if missing:
        titles = [next((a["title"] for a in ARTIFACT_KINDS if a["kind"] == k), k)
                  for k in missing]
        steps.append("Заполнить артефакты: " + ", ".join(titles))
    if not q1("SELECT id FROM c4_models WHERE service_id=? LIMIT 1", (svc["id"],)):
        steps.append("Нарисовать C4-модель (контекст/контейнеры) и экспортировать в Architecture Vision")
    if not (svc["owner"] or "").strip() or not (svc["domain"] or "").strip():
        steps.append("Заполнить карточку сервиса: владелец и домен")
    if svc["review_status"] == "draft":
        steps.append("Отправить сервис на ревью эксперту домена — готовность проверится автоматически")
    elif svc["review_status"] == "in_review":
        steps.append("Ожидается решение ревьюера")
    if not steps:
        steps.append("Готов к ревью — обязательные артефакты и ревью закрыты")
    return steps


@router.get("/services/{sid}")
def get_service(sid: int, user=Depends(current_user)):
    svc = q1("SELECT * FROM services WHERE id=?", (sid,))
    if not svc:
        raise HTTPException(404, "Сервис не найден")
    svc["my_scope"] = service_scope(user, svc)   # full / team / none — для UI
    svc["can_decide_review"] = has_global(user, "review.decide") or in_committee(user["username"])
    svc["mandatory_artifacts"] = _mandatory_kinds(svc["project_type"])
    svc["debts"] = [dict(r, ds=r["probability"] * r["damage"]) for r in
                    q("SELECT * FROM tech_debts WHERE service_id=? ORDER BY id DESC", (sid,))]
    svc["artifacts"] = q("SELECT * FROM artifacts WHERE service_id=? ORDER BY kind", (sid,))
    svc["checklist_runs"] = q("SELECT id,score_pct,mandatory_missing,created_by,created_at FROM checklist_runs"
                              " WHERE service_id=? ORDER BY created_at DESC LIMIT 10", (sid,))
    svc["reviews"] = q("SELECT * FROM reviews WHERE service_id=? ORDER BY requested_at DESC", (sid,))
    svc["components"] = q("""SELECT c.* FROM components c JOIN service_components sc ON sc.component_id=c.id
                              WHERE sc.service_id=?""", (sid,))
    svc["requirements"] = reqs.list_for(sid)             # ФТ/НФТ на сервисе
    _cov = reqs.coverage(sid)                            # покрытие: номер в артефактах
    for _r in svc["requirements"]:
        _r["covered_by"] = _cov.get(_r["id"], [])
    last = q1("SELECT answers FROM checklist_runs WHERE service_id=? ORDER BY created_at DESC LIMIT 1", (sid,))
    svc["last_answers"] = json.loads(last["answers"]) if last and last["answers"] else []
    svc["nfr"] = nfr.validate(sid)                       # MVP2 BR-51…53
    run = q1("SELECT id,passed,failed,warned,created_by,created_at FROM fitness_runs"
             " WHERE service_id=? ORDER BY created_at DESC LIMIT 1", (sid,))
    svc["fitness_last"] = dict(run) if run else None     # MVP2 BR-42
    svc["next_steps"] = _next_steps(svc)                 # живой список «что осталось»
    return svc


@router.get("/services/{sid}/readiness")
def service_readiness(sid: int, user=Depends(current_user)):
    """Живой ответ на вопрос «всё ли у меня есть перед отправкой на ревью» —
    без записи в БД (чек-ран фиксируется в момент отправки)."""
    svc = q1("SELECT * FROM services WHERE id=?", (sid,))
    if not svc:
        raise HTTPException(404, "Сервис не найден")
    answers = _auto_checklist(svc)
    blockers = _auto_blockers(svc, answers)
    pt_matrix = PROJECT_TYPES.get(svc["project_type"], {}).get("matrix", {})
    by_id = {it["id"]: it for it in CHECKLIST_ITEMS}
    # blocking — из матрицы типа проекта (как в _auto_blockers); matrix — для подписей UI
    def _matrix_status(it):
        return "mandatory" if it["artifact"] is None else pt_matrix.get(it["artifact"], "optional")
    items = [{"item_id": a["item_id"], "item": by_id[a["item_id"]]["item"],
              "weight": by_id[a["item_id"]]["weight"], "matrix": _matrix_status(by_id[a["item_id"]]),
              "grade": a["grade"], "link": a["link"],
              "blocking": a["grade"] != "E" and _matrix_status(by_id[a["item_id"]]) == "mandatory"}
             for a in answers]
    last = q1("SELECT score_pct, created_at, created_by FROM checklist_runs "
              "WHERE service_id=? ORDER BY created_at DESC LIMIT 1", (sid,))
    return {"service_id": sid, "ready": not blockers, "blockers": blockers,
            "score_pct": _checklist_score(answers), "items": items,
            "last_run": dict(last) if last else None}


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


# дочерние таблицы сервиса (FK REFERENCES services без ON DELETE CASCADE) —
# порядок не важен, но дочерние только одного уровня (вложенных FK нет)
_SERVICE_CHILD_TABLES = (
    "artifacts", "c4_models", "checklist_runs", "fitness_runs", "nfr_metrics",
    "requirements", "reviews", "service_components", "service_grants", "tech_debts",
    "ai_review_runs",
)


@router.delete("/services/{sid}")
def delete_service(sid: int, body=Body(default={}), user=Depends(current_user)):
    """Жёсткое удаление сервиса: только admin, с подтверждением кодом сервиса.

    Необратимо удаляет карточку и все дочерние данные (артефакты, ревью, техдолг…);
    история сохраняется только записью в audit_log. Для обратимого вывода из
    эксплуатации используйте PATCH lifecycle='decommissioned'.
    """
    if user["role"] != "admin":
        raise HTTPException(403, "Удаление сервиса доступно только admin "
                                 "(для вывода из эксплуатации используйте lifecycle)")
    svc = q1("SELECT * FROM services WHERE id=?", (sid,))
    if not svc:
        raise HTTPException(404, "Сервис не найден")
    if body.get("confirm") != svc["code"]:
        raise HTTPException(400, f"Подтвердите удаление: передайте confirm='{svc['code']}'")
    if svc["review_status"] == "in_review":
        raise HTTPException(409, "Сервис на ревью — сначала завершите или отзовите ревью")

    conn = get_conn()
    try:
        counts = {}
        for t in _SERVICE_CHILD_TABLES:
            cur = conn.execute(f"DELETE FROM {t} WHERE service_id=?", (sid,))
            counts[t] = cur.rowcount
        cur = conn.execute("DELETE FROM services WHERE id=?", (sid,))
        if cur.rowcount != 1:
            raise RuntimeError("service row not deleted")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    audit(user, "service_delete", f"service:{svc['code']}",
          "deleted rows: " + ", ".join(f"{t}:{n}" for t, n in counts.items() if n))
    return {"ok": True, "deleted": counts}


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
    # Готовность вычисляется автоматически из данных DeepArch (ручной self-check
    # упразднён); чек-ран фиксируется в момент отправки — история проверок сохраняется
    answers = _auto_checklist(svc)
    blockers = _auto_blockers(svc, answers)
    if blockers:
        raise HTTPException(409, "Сервис не готов к ревью — не закрыты обязательные пункты: "
                                 + "; ".join(blockers) + ". Заполните артефакты в DeepArch.")
    score_pct = _checklist_score(answers)
    exec("INSERT INTO checklist_runs(service_id,answers,score_pct,mandatory_missing,created_by,created_at) VALUES(?,?,?,?,?,?)",
         (sid, json.dumps(answers), score_pct, 0, user["username"], now()))
    audit(user, "self_check_auto", f"service:{svc['code']}", f"score={score_pct}% (авто при отправке на ревью)")
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


# ---------- AI-ревью до отправки (advisory, BR-33) ----------

@router.post("/services/{sid}/ai-review")
def ai_review_run(sid: int, body=Body(default={}), user=Depends(current_user)):
    """Двухслойное AI-ревью пакета: формальные проверки + содержательный LLM-проход.
    Advisory: находки не блокируют отправку (BR-33)."""
    svc = q1("SELECT * FROM services WHERE id=?", (sid,))
    if not svc:
        raise HTTPException(404, "Сервис не найден")
    if not can_edit_service(user, svc):
        raise HTTPException(403, "Нет прав на этот сервис")
    r = ai_review.run(sid, created_by=user["username"], model=(body.get("model") or "").strip())
    if not r:   # сервис удалён между проверкой и прогоном (TOCTOU)
        raise HTTPException(404, "Сервис не найден")
    serious = sum(1 for f in r["findings"] if f["severity"] == "warning")
    audit(user, "ai_review", f"service:{svc['code']}",
          f"formal={r['formal_count']} llm={r['llm_count']} serious={serious} provider={r['provider']}")
    return r


@router.get("/services/{sid}/ai-review")
def ai_review_last(sid: int, user=Depends(current_user)):
    if not q1("SELECT id FROM services WHERE id=?", (sid,)):
        raise HTTPException(404, "Сервис не найден")
    return ai_review.last(sid)


@router.post("/services/{sid}/ai-review/fix")
def ai_review_fix(sid: int, body=Body(default={}), user=Depends(current_user)):
    """Предложение исправления по находке AI-ревью (advisory, BR-33).

    Только надёжные типы: NFR profile из НФТ-требований, AI-черновик пустых/
    шаблонных Threat Model и DRP/BCP (с акцентом на находку). Ничего не
    сохраняет — автор смотрит предпросмотр и применяет через PUT artifacts.
    """
    svc = q1("SELECT * FROM services WHERE id=?", (sid,))
    if not svc:
        raise HTTPException(404, "Сервис не найден")
    if not can_edit_service(user, svc):
        raise HTTPException(403, "Нет прав на этот сервис")
    finding = {}
    for k in ("kind", "artifact_kind", "title", "detail", "std", "severity", "layer"):
        v = body.get(k)
        finding[k] = v.strip() if isinstance(v, str) else v
    r = ai_review.propose_fix(sid, finding, model=(body.get("model") or "").strip())
    if not r:
        raise HTTPException(400, "Эту находку нельзя исправить автоматически — правка за автором")
    audit(user, "ai_review_fix", f"service:{svc['code']}/{r['artifact_kind']}",
          f"strategy={r['strategy']} provider={r['provider']}")
    return r


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

@router.post("/ai/service-extract")
def ai_service_extract(body=Body(...), user=Depends(current_user)):
    """Design Session: из свободного документа → черновик карточки сервиса + требования.
    Advisory (BR-33): результат только предзаполняет форму создания, решение за человеком."""
    r = ai.extract_service(body.get("text") or "", model=(body.get("model") or "").strip())
    audit(user, "ai_service_extract", "-", f"provider:{r['provider']} reqs:{len(r['draft'].get('requirements') or [])}")
    return r


@router.post("/ai/draft")
def ai_draft(body=Body(...), user=Depends(current_user)):
    svc = q1("SELECT * FROM services WHERE id=?", (body.get("service_id"),))
    if not svc:
        raise HTTPException(404, "Сервис не найден")
    if not can_edit_service(user, svc):
        raise HTTPException(403, "Нет прав на этот сервис")
    r = ai.draft_artifact(body.get("service_id"), body.get("kind"),
                          model=(body.get("model") or "").strip())
    if not r:
        raise HTTPException(404, "Артефакт не найден")
    audit(user, "ai_draft", f"service:{body.get('service_id')}/{body.get('kind')}",
          f"provider:{r['provider']}")
    return r


@router.post("/services/{sid}/artifacts/scaffold")
def artifacts_scaffold(sid: int, user=Depends(current_user)):
    """Скелеты (шаблоны стандарта) для обязательных артефактов, которые ещё пусты."""
    svc = q1("SELECT * FROM services WHERE id=?", (sid,))
    if not svc:
        raise HTTPException(404, "Сервис не найден")
    if not can_edit_service(user, svc):
        raise HTTPException(403, "Нет прав на этот сервис")
    created = factory.scaffold_missing(sid, user["username"])
    if created:
        audit(user, "artifacts_scaffold", f"service:{sid}", f"kinds:{','.join(created)}")
    return {"created": created}


# ---------- Требования (ФТ/НФТ): вход в архитектурную работу ----------

@router.get("/services/{sid}/requirements")
def requirements_list(sid: int, user=Depends(current_user)):
    items = reqs.list_for(sid)
    cov = reqs.coverage(sid)
    for r in items:
        r["covered_by"] = cov.get(r["id"], [])
    return {"requirements": items}


@router.post("/services/{sid}/requirements")
def requirement_add(sid: int, body=Body(...), user=Depends(current_user)):
    """Ручное добавление одного требования."""
    svc = q1("SELECT * FROM services WHERE id=?", (sid,))
    if not svc:
        raise HTTPException(404, "Сервис не найден")
    if not can_edit_service(user, svc):
        raise HTTPException(403, "Нет прав на этот сервис")
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Нужен текст требования")
    typ = body.get("req_type") if body.get("req_type") in ("func", "nonfunc") else "func"
    created = reqs.import_items(sid, [{"req_type": typ, "text": text,
                                       "ext_id": (body.get("ext_id") or "").strip() or None}],
                                source_url=(body.get("source_url") or "").strip())
    audit(user, "requirement_add", f"service:{sid}", created[0]["ext_id"])
    return created[0]


@router.patch("/requirements/{rid}")
def requirement_patch(rid: int, body=Body(...), user=Depends(current_user)):
    r = q1("SELECT * FROM requirements WHERE id=?", (rid,))
    if not r:
        raise HTTPException(404, "Требование не найдено")
    svc = q1("SELECT * FROM services WHERE id=?", (r["service_id"],))
    if not can_edit_service(user, svc):
        raise HTTPException(403, "Нет прав на этот сервис")
    sets, args = [], []
    if "text" in body and (body["text"] or "").strip():
        sets.append("text=?"); args.append(body["text"].strip())
    if body.get("req_type") in ("func", "nonfunc"):
        sets.append("req_type=?"); args.append(body["req_type"])
    if body.get("status") in ("new", "in_work", "covered"):
        sets.append("status=?"); args.append(body["status"])
    if "source_url" in body:
        sets.append("source_url=?"); args.append((body["source_url"] or "").strip())
    if not sets:
        raise HTTPException(400, "Нечего обновлять")
    sets += ["updated_at=?"]; args += [now(), rid]
    exec(f"UPDATE requirements SET {', '.join(sets)} WHERE id=?", args)
    audit(user, "requirement_update", f"requirement:{rid}", ",".join(s[:-2] for s in sets[:-1]))
    return q1("SELECT * FROM requirements WHERE id=?", (rid,))


@router.delete("/requirements/{rid}")
def requirement_delete(rid: int, user=Depends(current_user)):
    r = q1("SELECT * FROM requirements WHERE id=?", (rid,))
    if not r:
        raise HTTPException(404, "Требование не найдено")
    svc = q1("SELECT * FROM services WHERE id=?", (r["service_id"],))
    if not can_edit_service(user, svc):
        raise HTTPException(403, "Нет прав на этот сервис")
    exec("DELETE FROM requirements WHERE id=?", (rid,))
    audit(user, "requirement_delete", f"requirement:{rid}", r["ext_id"])
    return {"ok": True}


@router.post("/services/{sid}/requirements/parse")
def requirements_parse(sid: int, body=Body(...), user=Depends(current_user)):
    """AI-разбор вставленного документа на требования (без сохранения — на подтверждение)."""
    svc = q1("SELECT * FROM services WHERE id=?", (sid,))
    if not svc:
        raise HTTPException(404, "Сервис не найден")
    if not can_edit_service(user, svc):
        raise HTTPException(403, "Нет прав на этот сервис")
    r = reqs.parse_document(body.get("text") or "", model=(body.get("model") or "").strip())
    audit(user, "requirements_parse", f"service:{sid}", f"provider:{r['provider']} items:{len(r['items'])}")
    return r


@router.post("/services/{sid}/requirements/import")
def requirements_import(sid: int, body=Body(...), user=Depends(current_user)):
    """Сохранение разобранных (и при желании поправленных) требований."""
    svc = q1("SELECT * FROM services WHERE id=?", (sid,))
    if not svc:
        raise HTTPException(404, "Сервис не найден")
    if not can_edit_service(user, svc):
        raise HTTPException(403, "Нет прав на этот сервис")
    items = body.get("items") or []
    if not isinstance(items, list) or not items:
        raise HTTPException(400, "Список requirements пуст")
    created = reqs.import_items(sid, items, source_url=(body.get("source_url") or "").strip())
    audit(user, "requirements_import", f"service:{sid}", f"n:{len(created)}")
    return {"created": created}


@router.post("/services/{sid}/nfr/from-requirements")
def nfr_from_requirements(sid: int, user=Depends(current_user)):
    """Черновик NFR & Security profile из НФТ-требований (возвращает markdown на подтверждение)."""
    svc = q1("SELECT * FROM services WHERE id=?", (sid,))
    if not svc:
        raise HTTPException(404, "Сервис не найден")
    if not can_edit_service(user, svc):
        raise HTTPException(403, "Нет прав на этот сервис")
    r = reqs.nfr_from_requirements(sid)
    if not r:
        raise HTTPException(400, "НФТ-требований нет — добавьте их в разделе «Требования»")
    audit(user, "nfr_from_requirements", f"service:{sid}", f"provider:{r['provider']}")
    return r


# ---------- Проектирование: визуальные C4-модели (L1/L2) ----------

@router.get("/services/{sid}/c4")
def c4_get(sid: int, user=Depends(current_user)):
    svc = q1("SELECT id FROM services WHERE id=?", (sid,))
    if not svc:
        raise HTTPException(404, "Сервис не найден")
    return {"models": c4mod.load(sid)}


@router.put("/services/{sid}/c4/{view}")
def c4_put(sid: int, view: str, body=Body(...), user=Depends(current_user)):
    svc = q1("SELECT * FROM services WHERE id=?", (sid,))
    if not svc:
        raise HTTPException(404, "Сервис не найден")
    if not can_edit_service(user, svc):
        raise HTTPException(403, "Нет прав на этот сервис")
    try:
        norm = c4mod.save(sid, view, body.get("model") or {}, user["username"])
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    # JSON-модель — источник правды: Mermaid-исходник в артефакте перегенерируется
    # автоматически (L1/L2 → vision_c4, ER → data_model); при блокирующих проблемах
    # модели запись не выполняется (gate не слабее)
    if view == "er":
        vs = c4mod.sync_data_model(sid)
        key = "dm"
    else:
        vs = c4mod.sync_vision(sid)
        key = "vision"
    note = (f" {key}:synced" if vs["synced"]
            else (f" {key}:skipped: " + "; ".join(vs["skipped"]) if vs["skipped"] else ""))
    audit(user, "c4_save", f"service:{sid}/{view}",
          f"nodes:{len(norm['nodes'])} edges:{len(norm['edges'])}" + note)
    return {"ok": True, "model": norm, f"{key}_synced": vs["synced"],
            f"{key}_skipped": vs["skipped"],
            **({f"{key}_code": vs["code"]} if vs["synced"] else {})}


@router.post("/services/{sid}/c4/{view}/ai")
def c4_ai(sid: int, view: str, body=Body(None), user=Depends(current_user)):
    """Сценарий 2: AI-структура C4-модели из фактов сервиса и требований (advisory)."""
    svc = q1("SELECT * FROM services WHERE id=?", (sid,))
    if not svc:
        raise HTTPException(404, "Сервис не найден")
    if not can_edit_service(user, svc):
        raise HTTPException(403, "Нет прав на этот сервис")
    r = c4mod.ai_design(sid, view, model=((body or {}).get("model") or "").strip())
    audit(user, "c4_ai", f"service:{sid}/{view}", f"provider:{r['provider']}")
    return r


@router.post("/services/{sid}/c4/export")
def c4_export(sid: int, body=Body(None), user=Depends(current_user)):
    """Экспорт обеих C4-моделей в Mermaid-исходник артефакта vision_c4.
    Перед записью — валидация (409 при блокирующих проблемах; force обходит осознанно)."""
    svc = q1("SELECT * FROM services WHERE id=?", (sid,))
    if not svc:
        raise HTTPException(404, "Сервис не найден")
    if not can_edit_service(user, svc):
        raise HTTPException(403, "Нет прав на этот сервис")
    report = c4mod.validate_models(sid)
    if body and body.get("dry_run"):
        return {"ok": True, "code": c4mod.build_code(sid), "validation": report}
    if report["blockers"] and not (body or {}).get("force"):
        audit(user, "c4_export_blocked", f"service:{sid}", "; ".join(report["blockers"]))
        raise HTTPException(409, "Валидация не пропускает экспорт: "
                            + "; ".join(report["blockers"]) + " (можно экспортировать принудительно)")
    r = c4mod.export_to_artifact(sid, user["username"])
    if not r.get("ok"):
        raise HTTPException(404, r.get("note", "не найдено"))
    r["validation"] = report
    audit(user, "c4_export", f"service:{sid}",
          f"updated:{r.get('updated')} len:{r.get('code_len', 0)}"
          + (f" forced ({'|'.join(report['blockers'])})" if report["blockers"] else ""))
    return r


@router.post("/ai/precheck")
def ai_precheck(user=Depends(current_user)):
    """Deprecated: AI Gate (mock-эвристика predict_checklist) поглощён AI-ревью —
    формальный слой нового механизма покрывает те же проверки."""
    raise HTTPException(410, "AI Gate упразднён: используйте POST /api/services/{id}/ai-review "
                             "(двухслойное AI-ревью до отправки, advisory BR-33)")


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

_KIND_TITLES = {a["kind"]: a["title"] for a in ARTIFACT_KINDS}

# человекочитаемые формулировки событий журнала для дашборда (advisory-подписи)
_ACTION_LABELS = {
    "login": "Вход в систему", "logout": "Выход",
    "create_service": "Создан сервис", "update_service": "Изменена карточка сервиса",
    "factory_scaffold": "Сгенерирован стартовый пакет",
    "save_artifact": "Обновлён артефакт", "artifacts_scaffold": "Заполнены скелеты артефактов",
    "c4_save": "Сохранена C4-модель", "c4_export": "Экспорт C4 в артефакт",
    "c4_export_blocked": "Экспорт C4 заблокирован валидацией",
    "self_check": "Пройден self-check", "ai_review": "AI-ревью пакета",
    "ai_precheck": "AI-предпроверка self-check (упразднена)",
    "ai_draft": "AI-черновик артефакта", "ai_service_extract": "Извлечение карточки из документа",
    "requirement_add": "Добавлено требование", "requirement_update": "Изменено требование",
    "requirement_delete": "Удалено требование", "requirements_parse": "Разобран документ требований",
    "requirements_import": "Импортированы требования", "nfr_from_requirements": "Черновик NFR из требований",
    "nfr_update": "Обновлён NFR-профиль", "request_review": "Запрошено ревью",
    "review_decision": "Решение по ревью", "debt_register": "Зарегистрирован техдолг",
    "debt_update": "Обновлён техдолг", "debt_status": "Изменён статус техдолга",
    "fitness_run": "Запущены fitness-проверки", "attach_component": "Подключён компонент",
    "create_component": "Создан компонент", "confluence_export": "Экспорт в Confluence",
    "confluence_import": "Импорт из Confluence", "backstage_import": "Импорт из Backstage",
    "llm_config": "Настройка LLM", "llm_test": "Проверка LLM",
    "set_role": "Изменена роль", "create_group": "Создана группа",
    "group_add_member": "Добавлен участник группы", "group_remove_member": "Удалён участник группы",
    "group_grant_service": "Группе выдан доступ к сервису", "group_revoke_service": "У группы отозван доступ",
}


def _human_activity(rows: list[dict]) -> list[dict]:
    """Дашборд-подача журнала: действие словами, entity «service:4/container» → «MPR /container».
    Исходные поля сохраняются (additive)."""
    codes = {r["id"]: r["code"] for r in q("SELECT id, code FROM services")}
    out = []
    for a in rows:
        m = re.match(r"service:(\d+)(/.*)?", a["entity"] or "")
        entity = a["entity"]
        if m:
            code = codes.get(int(m.group(1)), f"#svc-{m.group(1)}")
            entity = code + (m.group(2) or "")
        out.append({**a, "action_label": _ACTION_LABELS.get(a["action"], a["action"]),
                    "entity_label": entity})
    return out


@router.get("/dashboard")
def dashboard(user=Depends(current_user)):
    """Агрегаты главной страницы. Все ключи аддитивны: прежние потребители не ломаются."""
    total = q1("SELECT COUNT(*) AS n FROM services WHERE lifecycle != 'decommissioned'")["n"]
    archived = q1("SELECT COUNT(*) AS n FROM services WHERE lifecycle = 'decommissioned'")["n"]
    by_status = q("SELECT review_status, COUNT(*) AS n FROM services "
                  "WHERE lifecycle != 'decommissioned' GROUP BY review_status")
    latest = q("""SELECT s.id, s.code, s.name, s.review_status,
                  (SELECT score_pct FROM checklist_runs c WHERE c.service_id=s.id ORDER BY created_at DESC LIMIT 1) AS score
                  FROM services s WHERE s.lifecycle != 'decommissioned' ORDER BY s.updated_at DESC LIMIT 8""")
    comp_usage = q("""SELECT c.name, c.status, COUNT(sc.service_id) AS used_by
                       FROM components c LEFT JOIN service_components sc ON sc.component_id=c.id
                       GROUP BY c.id ORDER BY used_by DESC""")

    svcs = q("SELECT * FROM services WHERE lifecycle != 'decommissioned' ORDER BY updated_at DESC")
    # заполненные артефакты (не пустые) по сервисам
    filled = {}
    for a in q("SELECT service_id, kind FROM artifacts WHERE content_md != ''"):
        filled.setdefault(a["service_id"], set()).add(a["kind"])
    last_check = {r["service_id"]: r for r in q(
        "SELECT service_id, score_pct, mandatory_missing, MAX(created_at) AS m "
        "FROM checklist_runs GROUP BY service_id")}
    last_fit = {r["service_id"]: r for r in q(
        "SELECT service_id, passed, failed, warned, MAX(created_at) AS m "
        "FROM fitness_runs GROUP BY service_id")}
    open_debts = {r["service_id"]: dict(r) for r in q(
        "SELECT service_id, COUNT(*) AS n, "
        "SUM(CASE WHEN priority='P0' THEN 1 ELSE 0 END) AS p0, "
        "SUM(CASE WHEN priority='P1' THEN 1 ELSE 0 END) AS p1 "
        "FROM tech_debts WHERE status NOT IN ('repaid','cancelled') GROUP BY service_id")}

    # --- R1: готовность к ревью — составляющие отдельно, без «единой выдуманной цифры» ---
    def _hint(s, missing, ch, fit):
        # приоритет подсказки: заполнение → self-check → красный фитнес → статусы ревью;
        # вместе с текстом — целевая вкладка сервиса для клика с дашборда
        if missing:
            return ("Заполнить: " + ", ".join(_KIND_TITLES.get(k, k) for k in missing),
                    "artifacts")
        if not ch or ch["mandatory_missing"] > 0:
            return "Пройти self-check", "check"
        if fit and fit["failed"]:
            return f"Устранить красные фитнес-проверки ({fit['failed']})", "fitness"
        if s["review_status"] == "in_review":
            return "Ждёт решения по ревью", "review"
        if s["review_status"] == "changes_requested":
            return "Доработать по замечаниям", "review"
        if s["review_status"] == "approved":
            return "Согласовано", "review"
        return "Готов к запросу ревью", "review"

    readiness = []
    for s in svcs:
        mandatory = _mandatory_kinds(s["project_type"])
        missing = [k for k in mandatory if k not in filled.get(s["id"], set())]
        ch, fit, deb = last_check.get(s["id"]), last_fit.get(s["id"]), open_debts.get(s["id"], {})
        hint, hint_tab = _hint(s, missing, ch, fit)
        readiness.append({
            "id": s["id"], "code": s["code"], "name": s["name"],
            "review_status": s["review_status"],
            "mandatory_total": len(mandatory),
            "mandatory_missing": [{"kind": k, "title": _KIND_TITLES.get(k, k)} for k in missing],
            "self_check": ch["score_pct"] if ch else None,
            "fitness": ({"failed": fit["failed"], "warned": fit["warned"]} if fit else None),
            "debts_open": deb.get("n", 0), "debts_p0": deb.get("p0", 0), "debts_p1": deb.get("p1", 0),
            "hint": hint, "hint_link": f"/service/{s['id']}/{hint_tab}",
        })
    # сверху — сервисы с незакрытыми обязательными артефактами, затем с худшим self-check
    readiness.sort(key=lambda r: (-len(r["mandatory_missing"]),
                                  r["self_check"] if r["self_check"] is not None else 0))

    # --- R2: что ждёт меня ---
    my_tasks = {"pending_reviews": [], "blockers": []}
    if has_global(user, "review.decide") or in_committee(user["username"]):
        my_tasks["pending_reviews"] = q(
            "SELECT r.id, r.service_id, r.requested_by, r.requested_at, s.code, s.name "
            "FROM reviews r JOIN services s ON s.id = r.service_id "
            "WHERE r.status='in_review' ORDER BY r.requested_at DESC")
    for s in svcs:
        if service_scope(user, s) == "none":
            continue
        deb, fit = open_debts.get(s["id"], {}), last_fit.get(s["id"])
        why = []
        if s["review_status"] == "changes_requested":
            why.append("доработка после ревью")
        if fit and fit["failed"]:
            why.append(f"фитнес: {fit['failed']} красных")
        if deb.get("p0"):
            why.append(f"техдолг: P0 ×{deb['p0']}")
        if why:
            my_tasks["blockers"].append({"id": s["id"], "code": s["code"], "name": s["name"], "why": why})

    # --- R3: риски и техдолг ---
    debt_by_priority = q("SELECT priority, COUNT(*) AS n FROM tech_debts "
                         "WHERE status NOT IN ('repaid','cancelled') GROUP BY priority")
    debt_top = q(
        "SELECT d.debt_id, d.title, d.priority, d.risk, d.status, d.service_id, s.code, s.name "
        "FROM tech_debts d LEFT JOIN services s ON s.id = d.service_id "
        "WHERE d.status NOT IN ('repaid','cancelled') AND d.priority IN ('P0','P1') "
        "ORDER BY CASE d.priority WHEN 'P0' THEN 0 ELSE 1 END, "
        "CASE d.risk WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END LIMIT 5")

    # --- R5: покрытие процессом ---
    # «без self-check» = нет ни одного отвеченного прогона (create_service вставляет пустой run)
    coverage = {
        "no_requirements": q("SELECT id, code FROM services WHERE lifecycle != 'decommissioned' AND id NOT IN (SELECT DISTINCT service_id FROM requirements)"),
        "no_c4": q("SELECT id, code FROM services WHERE lifecycle != 'decommissioned' AND id NOT IN (SELECT DISTINCT service_id FROM c4_models)"),
        "no_checklist": q("SELECT id, code FROM services WHERE lifecycle != 'decommissioned' AND id NOT IN "
                          "(SELECT DISTINCT service_id FROM checklist_runs WHERE answers != '[]')"),
    }

    # --- R6: активность — только тем, у кого есть право на журнал аудита ---
    can_audit = has_global(user, "audit.view") or user["role"] == "admin"
    activity = _human_activity(
        q("SELECT ts, user, action, entity, detail FROM audit_log ORDER BY ts DESC LIMIT 12")
    ) if can_audit else []

    return {"total_services": total, "archived_services": archived, "by_review_status": by_status, "recent": latest,
            "component_usage": comp_usage, "standard_ref": STANDARD_REF,
            "readiness": readiness, "my_tasks": my_tasks,
            "debt_by_priority": debt_by_priority, "debt_top": debt_top,
            "coverage": coverage, "activity": activity}


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
    sql, args = ("SELECT d.*, s.code AS service_code, s.name AS service_name FROM tech_debts d"
                 " LEFT JOIN services s ON s.id = d.service_id WHERE 1=1"), []
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
        raise HTTPException(409, str(e)) from e
    audit(user, "factory_scaffold", f"service:{code}",
          f"artifacts:{r['artifacts']} components:{len(r['components_attached'])}")
    return r


# ---------- MVP2: RAG-ассистент (BR-48…50) ----------

def _chat_session(user_id: int, chat_id, first_text: str) -> int:
    """Id чата-сессии пользователя: существующий (проверка владельца) или новый.

    Новый чат получает title из первого вопроса.
    """
    if chat_id:
        r = q1("SELECT id FROM chat_sessions WHERE id=? AND user_id=?", (chat_id, user_id))
        if r:
            exec("UPDATE chat_sessions SET updated_at=? WHERE id=?", (now(), r["id"]))
            return r["id"]
    return exec("INSERT INTO chat_sessions(user_id,title,created_at,updated_at) "
                "VALUES(?,?,?,?)",
                (user_id, (first_text or "Новый чат")[:80], now(), now()))


def _chat_save(user_id: int, chat_id: int, role: str, content: str,
               provider: str | None = None, model: str | None = None,
               confidence: float | None = None, citations: list | None = None):
    """Сохранение реплики в чат (+ обрезка хвоста до 200 сообщений).

    Повторный user-вопрос в течение 10 секунд не дублируется
    (случай fallback-запроса после оборвавшегося стрима).
    """
    if role == "user":
        last = q1("SELECT role, content FROM chat_messages WHERE session_id=? "
                  "AND created_at > ? ORDER BY id DESC LIMIT 1", (chat_id, now() - 10))
        if last and last["role"] == "user" and last["content"] == content:
            return
    exec("INSERT INTO chat_messages(session_id,user_id,role,content,provider,model,"
         "confidence,citations,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
         (chat_id, user_id, role, content[:8000], provider, model, confidence,
          json.dumps(citations, ensure_ascii=False) if citations else None, now()))
    exec("DELETE FROM chat_messages WHERE session_id=? AND id NOT IN "
         "(SELECT id FROM chat_messages WHERE session_id=? ORDER BY id DESC LIMIT 200)",
         (chat_id, chat_id))
    exec("DELETE FROM chat_messages WHERE session_id=? AND id NOT IN "
         "(SELECT id FROM chat_messages WHERE session_id=? ORDER BY id DESC LIMIT 200)",
         (chat_id, chat_id))


def _chat_history(session_id: int, limit: int = 200) -> list[dict]:
    rows = q("SELECT * FROM chat_messages WHERE session_id=? "
             "ORDER BY id DESC LIMIT ?", (session_id, limit))
    out = []
    for r in reversed(rows):
        try:
            cites = json.loads(r["citations"]) if r["citations"] else []
        except ValueError:
            cites = []
        out.append({"role": r["role"], "content": r["content"],
                    "provider": r["provider"], "model": r["model"],
                    "confidence": r["confidence"], "citations": cites})
    return out


@router.get("/assistant/chats")
def assistant_chats(user=Depends(current_user)):
    """Список чатов пользователя для левой панели."""
    rows = q("SELECT id, title, updated_at FROM chat_sessions WHERE user_id=? "
             "ORDER BY updated_at DESC LIMIT 50", (user["id"],))
    return {"chats": rows}


@router.delete("/assistant/chats/{chat_id}")
def assistant_chat_delete(chat_id: int, user=Depends(current_user)):
    exec("DELETE FROM chat_messages WHERE session_id=? AND user_id=?", (chat_id, user["id"]))
    exec("DELETE FROM chat_sessions WHERE id=? AND user_id=?", (chat_id, user["id"]))
    return {"ok": True}


@router.get("/assistant/history")
def assistant_history(chat_id: int = 0, user=Depends(current_user)):
    if not chat_id:
        return {"messages": []}
    own = q1("SELECT id FROM chat_sessions WHERE id=? AND user_id=?", (chat_id, user["id"]))
    if not own:
        raise HTTPException(404, "Чат не найден")
    return {"messages": _chat_history(chat_id)}


@router.delete("/assistant/history")
def assistant_history_clear(user=Depends(current_user)):
    exec("DELETE FROM chat_messages WHERE user_id=?", (user["id"],))
    exec("DELETE FROM chat_sessions WHERE user_id=?", (user["id"],))
    return {"ok": True}


@router.get("/assistant/models")
def assistant_models(user=Depends(current_user)):
    """Список моделей для селектора в чате (любой авторизованный пользователь)."""
    _, _tok, model = llm.config()
    if not llm.configured():
        return {"models": [], "default": model}
    r = llm.list_models()
    return {"models": r["models"] or [model], "default": model}


@router.post("/assistant")
def assistant(body=Body(...), user=Depends(current_user)):
    question = (body.get("question") or "").strip()
    if not question:
        raise HTTPException(400, "Нужен question")
    history = body.get("history") or []
    if not isinstance(history, list):
        raise HTTPException(400, "history должен быть списком сообщений")
    clean = [{"role": m.get("role"), "content": (m.get("content") or "")[:2000]}
             for m in history[-6:] if isinstance(m, dict) and m.get("role") in ("user", "assistant")]
    model = (body.get("model") or "").strip()
    service_id = body.get("service_id")
    if service_id is not None and not isinstance(service_id, int):
        raise HTTPException(400, "service_id должен быть числом")
    chat_id = _chat_session(user["id"], body.get("chat_id"), question)
    _chat_save(user["id"], chat_id, "user", question)
    r = kb.answer(question, history=clean, model=model, service_id=service_id)
    _chat_save(user["id"], chat_id, "assistant", r["answer"], provider=r["provider"],
               model=r.get("model"), confidence=r.get("confidence"),
               citations=r.get("citations"))
    r["mode"] = "advisory"   # BR-33: решение за человеком
    r["chat_id"] = chat_id
    return r


@router.get("/assistant/status")
def assistant_status(user=Depends(current_user)):
    return kb.status()


@router.post("/assistant/stream")
def assistant_stream(body=Body(...), user=Depends(current_user)):
    """Стриминг ответа ассистента (SSE): meta → delta* → done → [DONE]."""
    question = (body.get("question") or "").strip()
    if not question:
        raise HTTPException(400, "Нужен question")
    history = body.get("history") or []
    if not isinstance(history, list):
        raise HTTPException(400, "history должен быть списком сообщений")
    clean = [{"role": m.get("role"), "content": (m.get("content") or "")[:2000]}
             for m in history[-6:] if isinstance(m, dict) and m.get("role") in ("user", "assistant")]
    model = (body.get("model") or "").strip()
    service_id = body.get("service_id")
    if service_id is not None and not isinstance(service_id, int):
        raise HTTPException(400, "service_id должен быть числом")
    chat_id = _chat_session(user["id"], body.get("chat_id"), question)
    _chat_save(user["id"], chat_id, "user", question)

    def gen():
        meta, parts = {}, []
        for ev in kb.answer_stream(question, history=clean, model=model,
                                   service_id=service_id):
            if ev["type"] == "meta":
                meta = ev
                ev = {**ev, "chat_id": chat_id}   # клиент запоминает чат
            elif ev["type"] == "delta":
                parts.append(ev["text"])
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        text = "".join(parts)
        if text:
            _chat_save(user["id"], chat_id, "assistant", text, provider=meta.get("provider"),
                       model=meta.get("model"), confidence=meta.get("confidence"),
                       citations=meta.get("citations"))
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


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
def llm_test(body=Body(None), user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Настройки LLM — только admin")
    body = body or {}
    r = llm.test_connection(url=body.get("url") or "",
                            token=body.get("token") or "",
                            model=body.get("model") or "")
    audit(user, "llm_test", "llm", f"ok={r['ok']} {r['latency_ms']}ms")
    return r


@router.post("/admin/llm/models")
def llm_models(body=Body(None), user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Настройки LLM — только admin")
    body = body or {}
    return llm.list_models(url=body.get("url") or "", token=body.get("token") or "")


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
