"""DeepArch MVP — клиент-серверная ИС проектирования и ревью архитектуры."""
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from .db import init_db
from .seed import seed
from .api import router

init_db()
seed()

app = FastAPI(title="DeepArch MVP", version="0.1.0",
              description="ИС проектирования/изменения/ревью архитектуры по корпоративному Architecture Definition Set")
app.include_router(router)

_static = os.path.join(os.path.dirname(__file__), "..", "web")
app.mount("/static", StaticFiles(directory=_static), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(_static, "index.html"))
