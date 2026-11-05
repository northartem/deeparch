"""NFR-валидация (MVP2 BR-51…53): цели из артефакта vs фактические метрики.

Извлекает целевые значения (RPS, p95, SLA, RTO, RPO) из артефакта NFR & Security
регулярными выражениями; хранит факт по каждому сервису; показывает статус:
ok (факт в пределах цели), breach (превышение), unknown (факт не измерен).
"""
import re
from .db import q, q1, exec, now

METRIC_NAMES = {"rps": "RPS (пиковый)", "p95_ms": "Время ответа p95, ms",
                "sla_pct": "SLA, %", "rto_h": "RTO, ч", "rpo_min": "RPO, мин"}

# RPS 500 / 500 rps / 500 RPS; p95 < 200ms; SLA 99.95%; RTO 4 часа; RPO 15 мин
PATTERNS = {
    "rps": (r"(\d[\d\s,]{0,12})\s*(?:rps|запросов\s*в\s*секунду)", 5000),
    "p95_ms": (r"p95[^.\n]{0,30}?(\d{2,5})\s*(?:ms|мс)", 3000),
    "sla_pct": (r"sla[^.\n%]{0,30}?(\d{2}(?:[.,]\d{1,3})?)\s*%", 100),
    "rto_h": (r"rto[^.\n\d]{0,30}?(\d{1,3})\s*(?:ч|час)", 24),
    "rpo_min": (r"rpo[^.\n\d]{0,30}?(\d{1,4})\s*(?:мин|minutes)", 60),
}


def extract_targets(service_id: int):
    """Достаёт цели из содержимого артефакта NFR & Security."""
    art = q1("SELECT content_md FROM artifacts WHERE service_id=? AND kind='nfr_security'",
             (service_id,))
    text = art["content_md"] if art else ""
    found = {}
    for metric, (pat, default) in PATTERNS.items():
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(" ", "").replace(",", ".")
            try:
                found[metric] = float(raw)
            except ValueError:
                pass
    return {"extracted": found, "artifact_present": bool(art and art["content_md"].strip())}


def apply_targets(service_id, user, metrics: dict):
    """Сохраняет извлечённые цели в nfr_metrics (не перезаписывая факт)."""
    saved = []
    for metric, value in metrics.items():
        if metric not in METRIC_NAMES or value is None:
            continue
        row = q1("SELECT id FROM nfr_metrics WHERE service_id=? AND metric=?",
                 (service_id, metric))
        if row:
            exec("UPDATE nfr_metrics SET target_value=? WHERE id=?", (value, row["id"]))
        else:
            exec("INSERT INTO nfr_metrics(service_id,metric,target_value,created_by,created_at)"
                 " VALUES(?,?,?,?,?)", (service_id, metric, value, user["username"], now()))
        saved.append(metric)
    return saved


def validate(service_id: int):
    """Цель vs факт: ok / breach / unknown. breach = факт хуже цели."""
    rows = q("SELECT * FROM nfr_metrics WHERE service_id=? ORDER BY metric", (service_id,))
    out = []
    for r in rows:
        m, t, a = r["metric"], r["target_value"], r["actual_value"]
        if a is None:
            status, detail = "unknown", "факт не измерен"
        else:
            if m in ("p95_ms", "rto_h", "rpo_min"):
                ok = a <= t
            else:  # rps, sla_pct: факт должен быть не ниже цели
                ok = a >= t
            status = "ok" if ok else "breach"
            detail = f"цель {t:g}, факт {a:g}" + ("" if ok else " — превышение/деградация")
        out.append({**dict(r), "status": status, "detail": detail})
    breaches = sum(1 for x in out if x["status"] == "breach")
    unknown = sum(1 for x in out if x["status"] == "unknown")
    return {"metrics": out, "breaches": breaches, "unknown": unknown,
            "verdict": "ok" if breaches == 0 and unknown == 0 else
                       ("breach" if breaches else "partial")}
