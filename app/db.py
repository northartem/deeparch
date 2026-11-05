"""SQLite-слой: инициализация схемы и простые хелперы."""
import sqlite3
import threading
import time
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "deeparch.db")
_local = threading.local()


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


def q(sql, params=()):
    cur = get_conn().execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    return rows


def q1(sql, params=()):
    rows = q(sql, params)
    return rows[0] if rows else None


def exec(sql, params=()):
    conn = get_conn()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.lastrowid


def now() -> float:
    return time.time()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  display_name TEXT NOT NULL,
  role TEXT NOT NULL,
  password_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS services (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  domain TEXT,
  owner TEXT,
  architect TEXT,
  project_type TEXT NOT NULL,
  lifecycle TEXT NOT NULL DEFAULT 'design',
  cmdb_id TEXT,
  catalog_source TEXT,
  review_status TEXT NOT NULL DEFAULT 'draft',
  created_at REAL, updated_at REAL
);

CREATE TABLE IF NOT EXISTS artifacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  service_id INTEGER NOT NULL REFERENCES services(id),
  kind TEXT NOT NULL,
  content_md TEXT NOT NULL DEFAULT '',
  diagram_code TEXT,                -- исходник диаграммы (Mermaid: C4/flowchart/erDiagram)
  source_url TEXT,
  version INTEGER NOT NULL DEFAULT 1,
  updated_by TEXT,
  updated_at REAL,
  UNIQUE(service_id, kind)
);

CREATE TABLE IF NOT EXISTS checklist_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  service_id INTEGER NOT NULL REFERENCES services(id),
  answers TEXT NOT NULL,            -- JSON: [{item_id, grade, link}]
  score_pct REAL NOT NULL,
  mandatory_missing INTEGER NOT NULL DEFAULT 0,
  created_by TEXT, created_at REAL
);

CREATE TABLE IF NOT EXISTS reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  service_id INTEGER NOT NULL REFERENCES services(id),
  requested_by TEXT, requested_at REAL,
  reviewer TEXT,
  status TEXT NOT NULL DEFAULT 'in_review',   -- in_review / approved / changes_requested
  comment TEXT,
  decided_at REAL
);

CREATE TABLE IF NOT EXISTS components (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL,
  kind TEXT NOT NULL,
  description TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'proposed',
  owner_team TEXT,
  standard_ref TEXT,
  adr_ref TEXT,
  repo_url TEXT,
  created_at REAL
);

CREATE TABLE IF NOT EXISTS service_components (
  service_id INTEGER NOT NULL REFERENCES services(id),
  component_id INTEGER NOT NULL REFERENCES components(id),
  PRIMARY KEY (service_id, component_id)
);

CREATE TABLE IF NOT EXISTS tech_debts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  debt_id TEXT UNIQUE NOT NULL,          -- TD-2026-11-001 / AD-2026-11-001 (правило DA)
  dtype TEXT NOT NULL,                   -- AD (архитектурный) / TD (технический)
  service_id INTEGER REFERENCES services(id),
  title TEXT NOT NULL,
  description TEXT DEFAULT '',
  cause TEXT DEFAULT '',                 -- причина возникновения
  arch_decision TEXT DEFAULT '',         -- какое решение породило долг
  target_state TEXT DEFAULT '',          -- целевое состояние
  consequences TEXT DEFAULT '',          -- последствия
  business_impact TEXT DEFAULT '',
  tech_impact TEXT DEFAULT '',
  risk TEXT NOT NULL DEFAULT 'Medium',   -- Low / Medium / High / Critical
  probability INTEGER NOT NULL DEFAULT 3,-- вероятность реализации риска 1–5
  damage INTEGER NOT NULL DEFAULT 3,     -- ущерб при реализации 1–5
  maintenance_cost TEXT DEFAULT '',      -- стоимость обслуживания долга
  repayment_cost TEXT DEFAULT '',        -- стоимость погашения
  owner TEXT,
  priority TEXT NOT NULL DEFAULT 'P2',   -- P0..P3
  status TEXT NOT NULL DEFAULT 'new',    -- new/accepted/planned/in_progress/repaid/cancelled
  review_date TEXT,                      -- срок пересмотра решения
  repayment_plan TEXT DEFAULT '',        -- план погашения (epic/действия)
  dependencies TEXT DEFAULT '',          -- затрагиваемые системы/инициативы
  created_by TEXT, created_at REAL,
  updated_at REAL
);

CREATE TABLE IF NOT EXISTS app_settings (    -- MVP2: настройки платформы (ключ-значение)
  key TEXT PRIMARY KEY,
  value TEXT
);

CREATE TABLE IF NOT EXISTS chat_sessions (   -- MVP2: чаты пользователя (список слева)
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  title TEXT NOT NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (   -- MVP2: история чата ассистента (по пользователю)
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES chat_sessions(id),
  user_id INTEGER NOT NULL REFERENCES users(id),
  role TEXT NOT NULL,                        -- 'user' | 'assistant'
  content TEXT NOT NULL,
  provider TEXT,                             -- ai-buddy | local-rag | none
  model TEXT,
  confidence REAL,
  citations TEXT,                            -- JSON [{page_id,title,url}]
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS fitness_rules (   -- MVP2 BR-41: правила-фитнес-функции
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  artifact_kind TEXT,                    -- к какому артефакту применяется
  check_kind TEXT NOT NULL,              -- diagram_source / contains / regex / minlen
  params TEXT NOT NULL DEFAULT '{}',     -- JSON: {"value":...,"path":...} 
  severity TEXT NOT NULL DEFAULT 'blocker',  -- blocker / warning
  standard_ref TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  created_at REAL
);

CREATE TABLE IF NOT EXISTS fitness_runs (    -- MVP2 BR-42: прогоны автопроверки
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  service_id INTEGER NOT NULL REFERENCES services(id),
  results TEXT NOT NULL,                 -- JSON: [{rule_id,name,verdict,detail}]
  passed INTEGER, failed INTEGER, warned INTEGER,
  created_by TEXT, created_at REAL
);

CREATE TABLE IF NOT EXISTS nfr_metrics (     -- MVP2 BR-51…53: цели vs факты
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  service_id INTEGER NOT NULL REFERENCES services(id),
  metric TEXT NOT NULL,                  -- rps / p95_ms / sla_pct / rto_h / rpo_min
  target_value REAL,
  target_note TEXT DEFAULT '',
  actual_value REAL,
  measured_at REAL,
  source TEXT DEFAULT '',
  created_by TEXT, created_at REAL,
  UNIQUE(service_id, metric)
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL, user TEXT, action TEXT, entity TEXT, detail TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  username TEXT NOT NULL,
  created_at REAL
);

CREATE TABLE IF NOT EXISTS groups (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL,
  kind TEXT NOT NULL DEFAULT 'product',   -- domain / committee / product / security
  description TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS group_members (
  group_id INTEGER NOT NULL REFERENCES groups(id),
  username TEXT NOT NULL,
  PRIMARY KEY (group_id, username)
);

CREATE TABLE IF NOT EXISTS service_grants (
  group_id INTEGER NOT NULL REFERENCES groups(id),
  service_id INTEGER NOT NULL REFERENCES services(id),
  PRIMARY KEY (group_id, service_id)
);
"""


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    # мягкая миграция для существующих БД
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(artifacts)").fetchall()]
    if "diagram_code" not in cols:
        conn.execute("ALTER TABLE artifacts ADD COLUMN diagram_code TEXT")
    ucols = [r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "password_hash" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
    mcols = [r["name"] for r in conn.execute("PRAGMA table_info(chat_messages)").fetchall()]
    if mcols and "session_id" not in mcols:
        conn.execute("ALTER TABLE chat_messages ADD COLUMN session_id INTEGER")
    conn.commit()
