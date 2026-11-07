"""
Ролевая модель (RBAC): роли x группы доступа x скоуп.

Роль = функциональные полномочия (что умеет).
Группа = организационная принадлежность (к чему применимо): domain / committee / product / security.
Доступ к конкретному сервису = роль эксперта/админа ИЛИ членство в product-группе,
которой грантован сервис ИЛИ владелец/архитектор в карточке.

Роли: admin, domain_expert, team_lead, infosec, viewer.
(«Чемпион» — не роль, а состав: чемпионы входят в product-группы своих команд.)
"""
from .db import q

# Полномочия, проверяемые глобально (вне скоупа сервиса)
GLOBAL_PERMS = {
    "admin":         {"user.manage", "integration.import", "audit.view", "component.manage",
                      "review.decide", "standard.manage"},
    "domain_expert": {"integration.import", "audit.view", "component.manage",
                      "review.decide", "standard.suggest"},
    "team_lead":     {"component.propose"},
    "infosec":       {"audit.view", "security.comment"},
    "viewer":        set(),
}

ROLE_RANK = {"viewer": 0, "team_lead": 1, "infosec": 1, "domain_expert": 2, "admin": 3}


def has_global(user, perm) -> bool:
    return perm in GLOBAL_PERMS.get(user["role"], set())


def user_groups(username: str):
    return q("""SELECT g.* FROM groups g JOIN group_members m ON m.group_id = g.id
                WHERE m.username = ? ORDER BY g.name""", (username,))


def group_services(group_id: int):
    return [r["service_id"] for r in
            q("SELECT service_id FROM service_grants WHERE group_id=?", (group_id,))]


def service_scope(user, svc) -> str:
    """full — все права на сервис; team — права команды; none — только чтение."""
    role = user["role"]
    if role in ("admin", "domain_expert"):
        return "full"
    if role == "team_lead":
        # 1) владелец/архитектор по карточке
        if user["username"] in (svc.get("owner"), svc.get("architect")):
            return "team"
        # 2) членство в product-группе, которой грантован сервис
        for g in user_groups(user["username"]):
            if g["kind"] == "product" and svc["id"] in group_services(g["id"]):
                return "team"
    return "none"


def can_edit_service(user, svc) -> bool:
    return service_scope(user, svc) in ("full", "team")


def in_committee(username: str) -> bool:
    return any(g["kind"] == "committee" for g in user_groups(username))
