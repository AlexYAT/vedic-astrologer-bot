"""Взаимодействие с OpenAI Assistants API."""

import logging
import time
from datetime import datetime
from typing import Literal, Optional, Tuple
from zoneinfo import ZoneInfo

# Тип возврата: (текст ответа, debug_info при DEBUG_MODE=1 иначе None)
AssistantResponse = Tuple[str, Optional[dict]]

from openai import OpenAI

import config
import db

from openai_safe import ASSISTANT_RUN_WAIT_TIMEOUT, HTTP_TIMEOUT, RunTimeoutError

logger = logging.getLogger(__name__)

_client: Optional[OpenAI] = None
_assistant_id_free: Optional[str] = None
_assistant_id_pro: Optional[str] = None

Mode = Literal["FREE", "PRO"]

# Статусы run: активные (не создаём новый run) и терминальные
_ACTIVE_RUN_STATUSES = ("queued", "in_progress", "requires_action")
_TERMINAL_STATUSES = ("completed", "failed", "cancelled", "expired")
RunStatus = Literal["completed", "failed", "cancelled", "expired", "timeout"]


def init_assistant(
    api_key: str,
    assistant_id_free: str,
    assistant_id_pro: str,
) -> None:
    """Инициализация клиента OpenAI и ID ассистентов FREE/PRO. HTTP timeout = HTTP_TIMEOUT с."""
    global _client, _assistant_id_free, _assistant_id_pro
    _client = OpenAI(api_key=api_key, timeout=float(HTTP_TIMEOUT))
    _assistant_id_free = assistant_id_free
    _assistant_id_pro = assistant_id_pro
    logger.info(
        "OpenAI Assistants API инициализирован (FREE/PRO, HTTP timeout=%s s, run wait=%s s)",
        HTTP_TIMEOUT,
        ASSISTANT_RUN_WAIT_TIMEOUT,
    )


def _get_client() -> OpenAI:
    if _client is None:
        raise RuntimeError("Assistant не инициализирован. Вызовите init_assistant().")
    return _client


def _assistant_id_suffix(assistant_id: str) -> str:
    """Последние 4 символа ID для логов (без полного ключа)."""
    return assistant_id[-4:] if len(assistant_id) >= 4 else "****"


def get_user_mode(telegram_id: int) -> Mode:
    """
    Эффективный режим пользователя для API: FREE или PRO.
    При visibility=testers только пользователи из MODE_SWITCH_USERS могут иметь PRO; остальным — FREE.
    Иначе — из БД (users.mode, учитывается pro_until).
    """
    visibility = config.get_mode_switch_visibility()
    if visibility == "testers" and telegram_id not in config.get_mode_switch_users():
        return "FREE"
    stored = db.get_user_mode(telegram_id)
    return "PRO" if stored == "pro" else "FREE"


def get_user_mode_and_suffix(telegram_id: int) -> Tuple[Mode, str]:
    """Режим и суффикс assistant_id для логов."""
    mode = get_user_mode(telegram_id)
    aid = _get_assistant_id_for_user(telegram_id)
    return mode, _assistant_id_suffix(aid)


def _get_assistant_id_for_user(telegram_id: int) -> str:
    """ID ассистента для данного пользователя (FREE или PRO)."""
    if _assistant_id_free is None or _assistant_id_pro is None:
        raise RuntimeError("Assistant не инициализирован. Вызовите init_assistant().")
    if get_user_mode(telegram_id) == "PRO":
        return _assistant_id_pro
    return _assistant_id_free


def _wrap_response(
    text: str,
    mode: str,
    assistant_id: str,
    thread_id: str,
    run_id: Optional[str],
    key: Optional[str] = None,
) -> AssistantResponse:
    """Вернуть (text, debug_info) при DEBUG_MODE=1, иначе (text, None). При DEBUG_MODE в debug_info добавляется key."""
    if config.get_debug_mode():
        debug_info = {
            "mode": mode.lower(),
            "assistant_id": assistant_id,
            "thread_id": thread_id,
            "run_id": run_id or "",
        }
        if key is not None:
            debug_info["key"] = key
        return (text, debug_info)
    return (text, None)


def get_or_create_thread(user_id: int, mode: str, request_type: Optional[str] = None) -> str:
    """
    Получить thread_id для пользователя и ключа (mode:group) или создать новый тред.
    key = "{mode}:{group}", где group = "check_action" при request_type=="check_action", иначе "forecast".
    Сохраняет thread_id в user_threads.
    """
    mode = (mode or "free").lower().strip()
    if mode not in ("free", "pro"):
        mode = "free"
    group = "check_action" if request_type == "check_action" else "forecast"
    key = f"{mode}:{group}"
    thread_id = db.get_thread_id(user_id, key)
    if thread_id:
        return thread_id

    client = _get_client()
    thread = client.beta.threads.create()
    thread_id = thread.id
    db.set_thread_id(user_id, key, thread_id)
    logger.info("Создан новый тред для user_id=%s key=%s: %s", user_id, key, thread_id)
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
    request_type: Optional[str] = None,
) -> AssistantResponse:
    """
    Отправить сообщение в тред, при необходимости создать run, дождаться завершения и вернуть ответ.
    Не создаёт новый run, если уже есть активный (queued/in_progress/requires_action).
    При истечении ожидания run выбрасывает openai_safe.RunTimeoutError (run_id, thread_id, elapsed_ms).

    :param timeout: макс. время ожидания завершения run (с); по умолчанию ASSISTANT_RUN_WAIT_TIMEOUT
    :param request_type: тип запроса для логов (today, tomorrow, check_action, topic, favorable)
    :return: (текст ответа, debug_info при DEBUG_MODE=1 иначе None)
    """
    max_wait_s = timeout if timeout is not None else ASSISTANT_RUN_WAIT_TIMEOUT
    client = _get_client()
    assistant_id = _get_assistant_id_for_user(user_id)
    mode = get_user_mode(user_id)
    aid_suffix = _assistant_id_suffix(assistant_id)
    thread_id = get_or_create_thread(user_id, mode.lower(), request_type)
    group = "check_action" if request_type == "check_action" else "forecast"
    thread_key = f"{mode.lower()}:{group}"

    logger.info(
        "request_type=%s telegram_id=%s mode=%s assistant_id=...%s thread_id=%s key=%s",
        request_type or "?",
        user_id,
        mode,
        aid_suffix,
        thread_id,
        thread_key,
    )

    # Текущая дата для контекста — timezone-aware, TZ_NAME (по умолчанию Asia/Novosibirsk)
    tz_name = config.get_tz_name()
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    today = datetime.now(tz).strftime("%d.%m.%Y")
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
                    "Run completed (existing) mode=%s assistant_id=...%s thread_id=%s run_id=%s elapsed_ms=%s",
                    mode,
                    aid_suffix,
                    thread_id,
                    run_id,
                    elapsed_ms,
                )
                text = _get_last_assistant_message(client, thread_id)
                return _wrap_response(text, mode, assistant_id, thread_id, run_id, key=thread_key)
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
            text = _get_last_assistant_message(client, thread_id)
            return _wrap_response(text, mode, assistant_id, thread_id, latest.id, key=thread_key)

    # 2) Нет активного run; добавляем сообщение и создаём run
    client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=enhanced_message,
    )
    logger.info("mode=%s assistant_id=...%s thread_id=%s", mode, aid_suffix, thread_id)
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
            "Run completed mode=%s assistant_id=...%s thread_id=%s run_id=%s elapsed_ms=%s",
            mode,
            aid_suffix,
            thread_id,
            run_id,
            elapsed_ms,
        )
        text = _get_last_assistant_message(client, thread_id)
        return _wrap_response(text, mode, assistant_id, thread_id, run_id, key=thread_key)

    if status == "failed":
        run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)
        error_msg = getattr(run, "last_error", None) or "Неизвестная ошибка"
        raise Exception(f"Ошибка выполнения ассистента: {error_msg}")
    raise Exception(f"Выполнение прервано: {status}")
