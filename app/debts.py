"""Модуль техдолга: генерация идентификаторов по правилу из Confluence (pageId=918365931).

Формат: {TYPE}-{ГГГГ}-{ММ}-{NNN}, где TYPE = TD (технический) / AD (архитектурный).
Счётчики AD и TD ведутся отдельно; номер обнуляется в начале каждого месяца;
ID присваивается один раз, неизменяем и не переиспользуется.
"""
from datetime import datetime
from .db import q


def gen_debt_id(dtype: str, registered_at: float) -> str:
    d = datetime.fromtimestamp(registered_at)
    prefix = f"{dtype}-{d.year}-{d.month:02d}-"
    maxn = 0
    for r in q("SELECT debt_id FROM tech_debts WHERE debt_id LIKE ?", (prefix + "%",)):
        try:
            maxn = max(maxn, int(r["debt_id"][len(prefix):]))
        except ValueError:
            pass
    n = maxn + 1
    return f"{prefix}{n:03d}" if n <= 999 else f"{prefix}{n}"   # >999 → 4 цифры
