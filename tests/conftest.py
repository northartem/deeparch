"""Фикстуры тестов: изолированная temp-БД, реальная deeparch.db не открывается.

DB_PATH переопределяется ДО импорта app.main (init_db + seed выполняются на temp-файле).
БД одна на сессию pytest — тесты используют собственные сервисы и не зависят
от точного количества объектов реестра.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db

_TMP_DIR = tempfile.mkdtemp(prefix="deeparch_test_")
db.DB_PATH = os.path.join(_TMP_DIR, "test.db")  # до импорта main: get_conn читает глобал при первом подключении

import pytest
from fastapi.testclient import TestClient

import app.main
from app.main import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="session")
def auth(client):
    def _tok(user):
        r = client.post("/api/login", json={"username": user, "password": "123456"})
        assert r.status_code == 200, r.text
        return {"X-Token": r.json()["token"]}
    return {"admin": _tok("admin"), "viewer": _tok("viewer"),
            "lead": _tok("lead"), "expert": _tok("expert")}


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP_DIR, ignore_errors=True)
