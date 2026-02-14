"""Взаимодействие с OpenAI Assistants API."""

import logging
import time
from typing import Optional

from openai import OpenAI

import db

logger = logging.getLogger(__name__)

_client: Optional[OpenAI] = None
_assistant_id: Optional[str] = None


def init_assistant(api_key: str, assistant_id: str) -> None:
    """Инициализация клиента OpenAI и ID ассистента."""
    global _client, _assistant_id
    _client = OpenAI(api_key=api_key)
    _assistant_id = assistant_id
    logger.info("OpenAI Assistants API инициализирован")


def _get_client() -> OpenAI:
    if _client is None:
        raise RuntimeError("Assistant не инициализирован. Вызовите init_assistant().")
    return _client


def _get_assistant_id() -> str:
    if _assistant_id is None:
        raise RuntimeError("ASSISTANT_ID не задан. Вызовите init_assistant().")
    return _assistant_id


def get_or_create_thread(user_id: int) -> str:
    """
    Получить thread_id для пользователя или создать новый тред.
    Сохраняет thread_id в БД при создании.
    """
    user = db.get_user(user_id)
    if user and user.get("thread_id"):
        return user["thread_id"]

    client = _get_client()
    thread = client.beta.threads.create()
    thread_id = thread.id
    db.update_user(user_id, thread_id=thread_id)
    logger.info("Создан новый тред для user_id=%s: %s", user_id, thread_id)
    return thread_id


def send_message_and_get_response(user_id: int, message: str, timeout: int = 120) -> str:
    """
    Отправить сообщение в тред пользователя, запустить ассистента и получить ответ.

    Raises:
        Exception: при ошибке API или превышении времени ожидания.
    """
    client = _get_client()
    assistant_id = _get_assistant_id()
    thread_id = get_or_create_thread(user_id)

    # Добавляем сообщение в тред
    client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=message
    )

    # Запускаем выполнение
    run = client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=assistant_id
    )

    # Ждём завершения выполнения
    start = time.time()
    while time.time() - start < timeout:
        run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)

        if run.status == "completed":
            break
        if run.status == "failed":
            error_msg = getattr(run, "last_error", None) or "Неизвестная ошибка"
            raise Exception(f"Ошибка выполнения ассистента: {error_msg}")
        if run.status in ("cancelled", "expired"):
            raise Exception(f"Выполнение прервано: {run.status}")

        time.sleep(1)

    if run.status != "completed":
        raise Exception("Превышено время ожидания ответа от ассистента")

    # Получаем последнее сообщение ассистента
    messages = client.beta.threads.messages.list(thread_id=thread_id, order="desc", limit=1)
    if not messages.data:
        raise Exception("Ассистент не вернул ответ")

    msg = messages.data[0]
    if msg.role != "assistant":
        raise Exception("Ожидался ответ ассистента")

    content = msg.content[0]
    if hasattr(content, "text"):
        return content.text.value
    return str(content)
