"""Клиент корпоративной LLM-платформы (AI-Buddy).

Контракт: OpenAI-совместимый chat/completions. Конфигурация берётся из настроек
платформы (таблица app_settings, ключи llm_url/llm_token/llm_model — задаются
в админ-панели) с приоритетом над переменными окружения:
  AI_BUDDY_URL    — базовый URL, напр. https://aibuddy.internal.company/v1
  AI_BUDDY_TOKEN  — сервисный токен
  AI_BUDDY_MODEL  — модель (по умолчанию ai-buddy-large)

Все вызовы advisory-only: ассистент только отвечает, решение за человеком (BR-33).
При отсутствии конфигурации или ошибке сети вызывающий код откатывается
на локальный извлекающий ответ из базы знаний (fallback в kb.py).
"""
import json
import os

import httpx

from .db import exec, q1

TIMEOUT = 30.0

LLM_KEYS = {"url": "llm_url", "token": "llm_token", "model": "llm_model"}


def _setting(key):
    r = q1("SELECT value FROM app_settings WHERE key=?", (key,))
    return r["value"] if r and r["value"] else None


def config():
    """Настройки LLM: БД (админ-панель) → env → дефолт модели."""
    url = _setting(LLM_KEYS["url"]) or os.environ.get("AI_BUDDY_URL", "")
    token = _setting(LLM_KEYS["token"]) or os.environ.get("AI_BUDDY_TOKEN", "")
    model = _setting(LLM_KEYS["model"]) or os.environ.get("AI_BUDDY_MODEL") \
        or "ai-buddy-large"
    return url.rstrip("/"), token, model


def source() -> str:
    """Откуда взята конфигурация: settings / env / none."""
    if _setting(LLM_KEYS["url"]):
        return "settings"
    if os.environ.get("AI_BUDDY_URL"):
        return "env"
    return "none"


def configured() -> bool:
    url, token, _ = config()
    return bool(url and token)


def save_settings(url: str, token: str, model: str):
    """Сохранение из админ-панели. Пустой token = оставить прежний."""
    for key, value in ((LLM_KEYS["url"], url.strip()),
                       (LLM_KEYS["model"], (model or "").strip() or "ai-buddy-large")):
        exec("INSERT INTO app_settings(key,value) VALUES(?,?) "
             "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    if token.strip():
        exec("INSERT INTO app_settings(key,value) VALUES(?,?) "
             "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
             (LLM_KEYS["token"], token.strip()))


def clear_settings():
    exec("DELETE FROM app_settings WHERE key IN (?,?,?)",
         tuple(LLM_KEYS.values()))


def masked_token() -> str:
    t = config()[1]
    return f"…{t[-4:]}" if len(t) >= 4 else ("задан" if t else "")


class LLMError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code   # HTTP-код, если ошибка от статуса ответа (для _tools_unsupported)


def list_models(url: str = "", token: str = "") -> dict:
    """Список моделей прокси: GET {url}/models (OpenAI-совместимый).

    Значения из формы приоритетнее сохранённых (как в test_connection).
    """
    cur_url, cur_token, _ = config()
    eff_url = (url or "").strip() or cur_url
    eff_token = (token or "").strip() or cur_token
    if not (eff_url and eff_token):
        return {"ok": False, "detail": "Не задан URL или токен — заполните поля формы",
                "models": []}
    try:
        r = httpx.get(f"{eff_url.rstrip('/')}/models",
                      headers={"Authorization": f"Bearer {eff_token}"}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        ids = sorted({m.get("id") for m in data.get("data", []) if m.get("id")})
        return {"ok": True, "detail": f"доступно моделей: {len(ids)}", "models": ids}
    except httpx.HTTPStatusError as e:
        body = e.response.text[:200]
        return {"ok": False, "detail": f"HTTP {e.response.status_code}: {body}", "models": []}
    except httpx.HTTPError as e:
        return {"ok": False, "detail": f"LLM недоступна: {e.__class__.__name__}: {e}",
                "models": []}
    except ValueError as e:
        return {"ok": False, "detail": f"Неожиданный формат ответа: {e}", "models": []}


def chat(messages: list[dict], temperature: float = 0.2, max_tokens: int = 2500,
         model: str = "") -> str:
    """messages: [{"role": "system"|"user"|"assistant", "content": str}] → текст ответа.

    model — переопределение модели (выбор в чате); пусто = модель из конфигурации.
    """
    url, token, def_model = config()
    if not (url and token):
        raise LLMError("AI-Buddy не сконфигурирован (админ-панель → Интеграции)")
    model = (model or "").strip() or def_model
    try:
        r = httpx.post(
            f"{url}/chat/completions",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json={"model": model, "messages": messages,
                  "temperature": temperature, "max_tokens": max_tokens,
                  "reasoning_effort": "low"},
            timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        # reasoning-модели могут вернуть content=None (весь бюджет ушёл в рассуждения)
        return data["choices"][0]["message"].get("content") or ""
    except httpx.HTTPStatusError as e:
        raise LLMError(f"HTTP {e.response.status_code}: {e.response.text[:200]}",
                       status_code=e.response.status_code) from e
    except httpx.HTTPError as e:
        raise LLMError(f"AI-Buddy недоступен: {e.__class__.__name__}") from e
    except (KeyError, IndexError, ValueError) as e:
        raise LLMError(f"Неожиданный формат ответа AI-Buddy: {e}") from e


def _payload(messages: list[dict], temperature: float, max_tokens: int, model: str,
             tools: list | None = None, stream: bool = False) -> dict:
    body = {"model": model, "messages": messages, "temperature": temperature,
            "max_tokens": max_tokens, "reasoning_effort": "low"}
    if tools:
        body["tools"] = tools
    if stream:
        body["stream"] = True
    return body


def chat_tools(messages: list[dict], tools: list[dict], temperature: float = 0.2,
               max_tokens: int = 2500, model: str = "") -> dict:
    """Вызов chat/completions с tools (OpenAI function calling).

    Возвращает нормализованное сообщение ассистента:
      {"content": str}                                  — финальный ответ, или
      {"content": str, "tool_calls": [{id,name,arguments}]} — запрос вызова инструментов.
    arguments — сырая JSON-строка от модели (может быть невалидной, парсит вызывающий).
    Бросает LLMError при ошибке, в т.ч. если прокси/модель не поддерживают tools.
    """
    url, token, def_model = config()
    if not (url and token):
        raise LLMError("AI-Buddy не сконфигурирован (админ-панель → Интеграции)")
    model = (model or "").strip() or def_model
    try:
        r = httpx.post(
            f"{url}/chat/completions",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json=_payload(messages, temperature, max_tokens, model, tools=tools),
            timeout=TIMEOUT)
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        calls = []
        for i, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function") or {}
            args = fn.get("arguments")
            # некоторые шлюзы отдают arguments уже объектом — нормализуем в строку
            if isinstance(args, dict):
                args = json.dumps(args, ensure_ascii=False)
            calls.append({"id": tc.get("id") or f"call_{i}",
                          "name": fn.get("name") or "", "arguments": args or "{}"})
        return {"content": msg.get("content") or "", "tool_calls": calls}
    except httpx.HTTPStatusError as e:
        raise LLMError(f"HTTP {e.response.status_code}: {e.response.text[:200]}",
                       status_code=e.response.status_code) from e
    except httpx.HTTPError as e:
        raise LLMError(f"AI-Buddy недоступен: {e.__class__.__name__}") from e
    except (KeyError, IndexError, ValueError) as e:
        raise LLMError(f"Неожиданный формат ответа AI-Buddy: {e}") from e


def chat_stream(messages: list[dict], temperature: float = 0.2, max_tokens: int = 2500,
                model: str = ""):
    """Стриминг ответа: генератор дельт текста (OpenAI stream=true, SSE).

    model — переопределение модели (выбор в чате); пусто = модель из конфигурации.
    Бросает LLMError при отсутствии конфигурации / сетевой ошибке / HTTP-ошибке.
    """
    url, token, def_model = config()
    if not (url and token):
        raise LLMError("AI-Buddy не сконфигурирован (админ-панель → Интеграции)")
    model = (model or "").strip() or def_model
    try:
        with httpx.stream(
                "POST", f"{url}/chat/completions",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
                json=_payload(messages, temperature, max_tokens, model, stream=True),
                timeout=TIMEOUT) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    delta = json.loads(data)["choices"][0]["delta"].get("content")
                except (KeyError, IndexError, ValueError):
                    continue
                if delta:
                    yield delta
    except httpx.HTTPStatusError as e:
        raise LLMError(f"HTTP {e.response.status_code}: {e.response.read()[:200]!r}",
                       status_code=e.response.status_code) from e
    except httpx.HTTPError as e:
        raise LLMError(f"AI-Buddy недоступен: {e.__class__.__name__}") from e


def _accumulate_tool_delta(acc: dict, delta: dict) -> dict:
    """Накопление разорванных дельт tool_calls (OpenAI-стриминг) — чистая функция для тестов.

    delta — объект delta из SSE-чанка; acc — {index: {id,name,arguments}}.
    Шлюзы без поля index: каждая новая запись с именем открывает новый слот.
    """
    for tc in delta.get("tool_calls") or []:
        i = tc.get("index")
        if i is None:
            i = len(acc) if (tc.get("function") or {}).get("name") else (max(acc) if acc else 0)
        a = acc.setdefault(i, {"id": "", "name": "", "arguments": ""})
        if tc.get("id"):
            a["id"] = tc["id"]
        fn = tc.get("function") or {}
        if fn.get("name"):
            a["name"] = fn["name"]
        if fn.get("arguments"):
            a["arguments"] += fn["arguments"]
    return acc


def chat_stream_tools(messages: list[dict], tools: list[dict], temperature: float = 0.2,
                      max_tokens: int = 2500, model: str = ""):
    """Стриминг с tools: генератор событий
      {"type":"delta", "text": str}                       — дельта контента, или
      {"type":"tool_calls", "tool_calls": [{id,name,arguments}]} — в конце раунда.

    Дельты tool_calls (разорванные фрагменты arguments) накапливаются по index.
    Бросает LLMError при ошибке, в т.ч. если прокси/модель не поддерживают tools.
    """
    url, token, def_model = config()
    if not (url and token):
        raise LLMError("AI-Buddy не сконфигурирован (админ-панель → Интеграции)")
    model = (model or "").strip() or def_model
    acc: dict[int, dict] = {}
    try:
        with httpx.stream(
                "POST", f"{url}/chat/completions",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
                json=_payload(messages, temperature, max_tokens, model, tools=tools,
                              stream=True),
                timeout=TIMEOUT) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    delta = json.loads(data)["choices"][0].get("delta") or {}
                except (KeyError, IndexError, ValueError):
                    continue
                if delta.get("content"):
                    yield {"type": "delta", "text": delta["content"]}
                _accumulate_tool_delta(acc, delta)
    except httpx.HTTPStatusError as e:
        raise LLMError(f"HTTP {e.response.status_code}: {e.response.read()[:200]!r}",
                       status_code=e.response.status_code) from e
    except httpx.HTTPError as e:
        raise LLMError(f"AI-Buddy недоступен: {e.__class__.__name__}") from e
    if acc:
        calls = []
        for i, a in sorted(acc.items()):
            calls.append({**a, "id": a["id"] or f"call_{i}",
                          "arguments": a["arguments"] or "{}"})
        yield {"type": "tool_calls", "tool_calls": calls}


def test_connection(url: str = "", token: str = "", model: str = "") -> dict:
    """Проверка связи из админ-панели.

    Значения из формы админ-панели имеют приоритет: можно проверить связь
    до сохранения. Пустой token = использовать сохранённый (если есть).
    """
    import time
    cur_url, cur_token, cur_model = config()
    eff_url = (url or "").strip() or cur_url
    eff_token = (token or "").strip() or cur_token
    eff_model = (model or "").strip() or cur_model
    t0 = time.monotonic()
    try:
        if not (eff_url and eff_token):
            raise LLMError("Не задан URL или токен — заполните поля формы "
                           "(проверка использует значения из формы, сохранение кнопкой «Подключить»)")
        r = httpx.post(
            f"{eff_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {eff_token}",
                     "Content-Type": "application/json"},
            json={"model": eff_model,
                  "messages": [{"role": "user", "content": "Ответь одним словом: ping"}],
                  "temperature": 0.0, "max_tokens": 16},
            timeout=TIMEOUT)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        return {"ok": True, "detail": f"LLM ответила: {text.strip()[:80]!r}",
                "latency_ms": int((time.monotonic() - t0) * 1000)}
    except LLMError as e:
        return {"ok": False, "detail": str(e),
                "latency_ms": int((time.monotonic() - t0) * 1000)}
    except httpx.HTTPStatusError as e:
        body = e.response.text[:300]
        return {"ok": False, "detail": f"HTTP {e.response.status_code}: {body}",
                "latency_ms": int((time.monotonic() - t0) * 1000)}
    except httpx.HTTPError as e:
        return {"ok": False, "detail": f"LLM недоступна: {e.__class__.__name__}: {e}",
                "latency_ms": int((time.monotonic() - t0) * 1000)}
    except (KeyError, IndexError, ValueError) as e:
        return {"ok": False, "detail": f"Неожиданный формат ответа: {e}",
                "latency_ms": int((time.monotonic() - t0) * 1000)}
