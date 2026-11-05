"""Аутентификация (логин + пароль → сессионный токен) и иерархия ролей."""
import hashlib
import secrets
from fastapi import Header, HTTPException
from .db import q1

ROLE_RANK = {"viewer": 0, "team_lead": 1, "infosec": 1, "domain_expert": 2, "admin": 3}


def hash_password(password: str, salt: str | None = None) -> str:
    """PBKDF2-SHA256, формат 'salt$hash'."""
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${h}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
    except (ValueError, AttributeError):
        return False
    return secrets.compare_digest(hash_password(password, salt), stored)


def current_user(x_token: str = Header(default=None)):
    if not x_token:
        raise HTTPException(401, "Нет токена авторизации — выполните вход")
    user = q1("SELECT u.* FROM users u JOIN sessions s ON s.username = u.username WHERE s.token=?",
              (x_token,))
    if not user:
        raise HTTPException(401, "Сессия недействительна — войдите заново")
    return user


def require_role(user, minimum: str):
    if ROLE_RANK[user["role"]] < ROLE_RANK[minimum]:
        raise HTTPException(403, f"Требуется роль {minimum}+, у вас: {user['role']}")
    return user
