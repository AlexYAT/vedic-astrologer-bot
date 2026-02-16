"""Взаимодействие с OpenAI Assistants API."""

import logging
import time
from datetime import datetime
from typing import Literal, Optional

from openai import OpenAI

import db

from openai_safe import ASSISTANT_RUN_WAIT_TIMEOUT, HTTP_TIMEOUT, RunTimeoutError

logger = logging.getLogger(__name__)

_client: Optional[OpenAI] = None
_assistant_id: Optional[str] = None

# Статусы run: активные (не создаём новый run) и терминальные
_ACTIVE_RUN_STATUSES = ("queued", "in_progress", "requires_action")
_TERMINAL_STATUSES = ("completed", "failed", "cancelled", "expired")
RunStatus = Literal["completed", "failed", "cancelled", "expired", "timeout"]


def init_assistant(api_key: str, assistant_id: str) -> None:
    """Инициализация клиента OpenAI и ID ассистента. HTTP timeout = HTTP_TIMEOUT с."""
    global _client, _assistant_id
    _client = OpenAI(api_key=api_key, timeout=float(HTTP_TIMEOUT))
    _assistant_id = assistant_id
    logger.info(
        "OpenAI Assistants API инициализирован (HTTP timeout=%s s, run wait=%s s)",
        HTTP_TIMEOUT,
        ASSISTANT_RUN_WAIT_TIMEOUT,
    )


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


def _get_latest_run(client: OpenAI, thread_id: str):
    """Последний run в треде (или None)."""
    runs = client.beta.threads.runs.list(thread_id=thread_id, limit=1, order="desc")
    if not runs.data:
        return None
    return runs.data[0]


def wait_run_complete(
    thread_id: str,
    run_id: str,
    max_wait_s: int = 60,
    poll_interval_s: float = 1.2,
) -> RunStatus:
    """
    Ожидание завершения run: опрос GET runs/{run_id} каждые poll_interval_s.
    Выход при status in (completed, failed, cancelled, expired) или по истечении max_wait_s.
    Возвращает финальный status или "timeout".
    """
    client = _get_client()
    start = time.monotonic()
    while True:
        run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)
        if run.status in _TERMINAL_STATUSES:
            return run.status  # type: ignore[return-value]
        if time.monotonic() - start >= max_wait_s:
            return "timeout"
        time.sleep(poll_interval_s)


def _get_last_assistant_message(client: OpenAI, thread_id: str) -> str:
    """Последнее сообщение ассистента в треде."""
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


def send_message_and_get_response(
    user_id: int,
    message: str,
    timeout: Optional[int] = None,
) -> str:
    """
    Отправить сообщение в тред, при необходимости создать run, дождаться завершения и вернуть ответ.
    Не создаёт новый run, если уже есть активный (queued/in_progress/requires_action).
    При истечении ожидания run выбрасывает openai_safe.RunTimeoutError (run_id, thread_id, elapsed_ms).

    :param timeout: макс. время ожидания завершения run (с); по умолчанию ASSISTANT_RUN_WAIT_TIMEOUT
    """
    max_wait_s = timeout if timeout is not None else ASSISTANT_RUN_WAIT_TIMEOUT
    client = _get_client()
    assistant_id = _get_assistant_id()
    thread_id = get_or_create_thread(user_id)

    # Текущая дата для контекста
    today = datetime.now().strftime("%d.%m.%Y")
    enhanced_message = f"Сегодня {today}. {message}"

    start = time.monotonic()
    run_id: Optional[str] = None

    # 1) Есть ли уже активный или только что завершённый run?
    latest = _get_latest_run(client, thread_id)
    if latest is not None:
        if latest.status in _ACTIVE_RUN_STATUSES:
            # Ждём существующий run, новый не создаём
            run_id = latest.id
            logger.info(
                "Ожидание существующего run thread_id=%s run_id=%s",
                thread_id,
                run_id,
            )
            status = wait_run_complete(thread_id, run_id, max_wait_s=max_wait_s, poll_interval_s=1.2)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            if status == "timeout":
                logger.warning(
                    "Run wait timeout thread_id=%s run_id=%s elapsed_ms=%s",
                    thread_id,
                    run_id,
                    elapsed_ms,
                )
                raise RunTimeoutError(run_id=run_id, thread_id=thread_id, elapsed_ms=elapsed_ms)
            if status == "completed":
                logger.info(
                    "Run completed (existing) thread_id=%s run_id=%s elapsed_ms=%s",
                    thread_id,
                    run_id,
                    elapsed_ms,
                )
                return _get_last_assistant_message(client, thread_id)
            if status == "failed":
                run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)
                err = getattr(run, "last_error", None) or "Неизвестная ошибка"
                raise Exception(f"Ошибка выполнения ассистента: {err}")
            raise Exception(f"Выполнение прервано: {status}")

        if latest.status == "completed":
            # Уже есть готовый ответ — возвращаем его (повторный запрос после таймаута)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "Используем последний завершённый run thread_id=%s run_id=%s elapsed_ms=%s",
                thread_id,
                latest.id,
                elapsed_ms,
            )
            return _get_last_assistant_message(client, thread_id)

    # 2) Нет активного run; добавляем сообщение и создаём run
    client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=enhanced_message,
    )
    run = client.beta.threads.runs.create(thread_id=thread_id, assistant_id=assistant_id)
    run_id = run.id

    status = wait_run_complete(thread_id, run_id, max_wait_s=max_wait_s, poll_interval_s=1.2)
    elapsed_ms = int((time.monotonic() - start) * 1000)

    if status == "timeout":
        logger.warning(
            "Run wait timeout thread_id=%s run_id=%s elapsed_ms=%s",
            thread_id,
            run_id,
            elapsed_ms,
        )
        raise RunTimeoutError(run_id=run_id, thread_id=thread_id, elapsed_ms=elapsed_ms)

    if status == "completed":
        logger.info(
            "Run completed thread_id=%s run_id=%s elapsed_ms=%s",
            thread_id,
            run_id,
            elapsed_ms,
        )
        return _get_last_assistant_message(client, thread_id)

    if status == "failed":
        run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)
        error_msg = getattr(run, "last_error", None) or "Неизвестная ошибка"
        raise Exception(f"Ошибка выполнения ассистента: {error_msg}")
    raise Exception(f"Выполнение прервано: {status}")
