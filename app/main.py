"""DeepArch MVP — клиент-серверная ИС проектирования и ревью архитектуры."""
import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .db import init_db
from .seed import seed

init_db()
seed()

app = FastAPI(title="DeepArch MVP", version="0.1.0",
              description="ИС проектирования/изменения/ревью архитектуры по корпоративному Architecture Definition Set")
app.include_router(router)

_static = os.path.join(os.path.dirname(__file__), "..", "web")
app.mount("/static", StaticFiles(directory=_static), name="static")

# Статика кэшируется браузером жёстко (профиль, не сессия): без ?v= после обновления
# пользователь остаётся на старом app.js/styles.css, и «ничего не работает» без причины.
_VERSIONED = ("app.js", "styles.css", "vendor/mermaid.min.js")


def _index_html() -> str:
    with open(os.path.join(_static, "index.html"), encoding="utf-8") as f:
        html = f.read()
    for name in _VERSIONED:
        try:
            v = int(os.stat(os.path.join(_static, name)).st_mtime)
        except OSError:
            continue
        html = html.replace(f"/static/{name}", f"/static/{name}?v={v}")
    return html


@app.get("/")
def index():
    return HTMLResponse(_index_html())
