"""Клиент корпоративной LLM-платформы (AI-Buddy).

Контракт: OpenAI-совместимый chat/completions. Конфигурация через переменные
окружения:
  AI_BUDDY_URL    — базовый URL, напр. https://aibuddy.internal.company/v1
  AI_BUDDY_TOKEN  — сервисный токен
  AI_BUDDY_MODEL  — модель (по умолчанию ai-buddy-large)

Все вызовы advisory-only: ассистент только отвечает, решение за человеком (BR-33).
При отсутствии конфигурации или ошибке сети вызывающий код откатывается
на локальный извлекающий ответ из базы знаний (fallback в kb.py).
"""
import os
import httpx

TIMEOUT = 30.0


def config():
    url = os.environ.get("AI_BUDDY_URL", "").rstrip("/")
    token = os.environ.get("AI_BUDDY_TOKEN", "")
    model = os.environ.get("AI_BUDDY_MODEL", "ai-buddy-large")
    return url, token, model


def configured() -> bool:
    url, token, _ = config()
    return bool(url and token)


class LLMError(Exception):
    pass


def chat(messages: list[dict], temperature: float = 0.2, max_tokens: int = 900) -> str:
    """messages: [{"role": "system"|"user"|"assistant", "content": str}] → текст ответа."""
    url, token, model = config()
    if not (url and token):
        raise LLMError("AI-Buddy не сконфигурирован (AI_BUDDY_URL / AI_BUDDY_TOKEN)")
    try:
        r = httpx.post(
            f"{url}/chat/completions",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json={"model": model, "messages": messages,
                  "temperature": temperature, "max_tokens": max_tokens},
            timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except httpx.HTTPError as e:
        raise LLMError(f"AI-Buddy недоступен: {e.__class__.__name__}") from e
    except (KeyError, IndexError, ValueError) as e:
        raise LLMError(f"Неожиданный формат ответа AI-Buddy: {e}") from e
