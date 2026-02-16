"""
Обёртка вызовов OpenAI с таймаутом и единой обработкой ошибок.
Таймаут ожидания run (60s) ≠ «сервис недоступен»: при run timeout возвращается RUN_TIMEOUT_SENTINEL.
"""

import asyncio
import logging
import time
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

# HTTP timeout для каждого запроса к API (используется в assistant через init)
HTTP_TIMEOUT = 30
# Таймаут ожидания завершения run (опрос status); при истечении — RUN_TIMEOUT_SENTINEL, не «сервис недоступен»
ASSISTANT_RUN_WAIT_TIMEOUT = 60
# Для обратной совместимости: общий таймаут вызова ассистента = run wait
ASSISTANT_TIMEOUT = ASSISTANT_RUN_WAIT_TIMEOUT
VALIDATION_TIMEOUT = 12

MSG_SERVICE_UNAVAILABLE = (
    "⚠️ Сервис временно недоступен. Пожалуйста, попробуйте чуть позже."
)
MSG_RUN_TIMEOUT = (
    "⏳ Ответ готовится дольше обычного. Попробуйте ещё раз через минуту."
)

# Специальный результат при таймауте ожидания run (не создаём новый run, не «сервис недоступен»)
RUN_TIMEOUT_SENTINEL = object()


class RunTimeoutError(Exception):
    """Исключение при истечении ожидания завершения run (без ошибки API)."""

    __slots__ = ("run_id", "thread_id", "elapsed_ms")

    def __init__(
        self,
        run_id: str,
        thread_id: str,
        elapsed_ms: int,
    ) -> None:
        self.run_id = run_id
        self.thread_id = thread_id
        self.elapsed_ms = elapsed_ms
        super().__init__(f"run_id={run_id} thread_id={thread_id} elapsed_ms={elapsed_ms}")


T = TypeVar("T")


def _context_str(
    request_type: str | None = None,
    telegram_id: int | None = None,
    run_id: str | None = None,
    thread_id: str | None = None,
    elapsed_ms: int | None = None,
) -> str:
    parts = []
    if request_type is not None:
        parts.append(f"request_type={request_type}")
    if telegram_id is not None:
        parts.append(f"telegram_id={telegram_id}")
    if run_id is not None:
        parts.append(f"run_id={run_id}")
    if thread_id is not None:
        parts.append(f"thread_id={thread_id}")
    if elapsed_ms is not None:
        parts.append(f"elapsed_ms={elapsed_ms}")
    return " | ".join(parts) if parts else ""


async def safe_openai_call(
    sync_func: Callable[[], T],
    timeout: int = ASSISTANT_RUN_WAIT_TIMEOUT,
    request_type: str | None = None,
    telegram_id: int | None = None,
) -> T | None:
    """
    Выполняет синхронный вызов OpenAI в executor с таймаутом.
    - При RunTimeoutError: логирует WARNING (run_id, thread_id, ...), возвращает RUN_TIMEOUT_SENTINEL.
    - При asyncio.TimeoutError или других ошибках: логирует ERROR, возвращает None (сервис недоступен).

    :return: результат sync_func(), None при ошибке API, RUN_TIMEOUT_SENTINEL при таймауте ожидания run
    """
    start = time.monotonic()
    try:
        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, sync_func),
            timeout=float(timeout),
        )
        return result
    except RunTimeoutError as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        ctx = _context_str(
            request_type=request_type,
            telegram_id=telegram_id,
            run_id=e.run_id,
            thread_id=e.thread_id,
            elapsed_ms=e.elapsed_ms,
        )
        logger.warning(
            "Run wait timeout (ответ готовится дольше). %s",
            ctx,
        )
        return RUN_TIMEOUT_SENTINEL  # type: ignore[return-value]
    except asyncio.TimeoutError as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        ctx = _context_str(request_type=request_type, telegram_id=telegram_id, elapsed_ms=elapsed_ms)
        logger.error(
            "OpenAI call timeout after %s s. Увеличьте таймаут или проверьте сеть. %s%s",
            timeout,
            (" [" + ctx + "] ") if ctx else "",
            e,
        )
        return None
    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        ctx = _context_str(request_type=request_type, telegram_id=telegram_id, elapsed_ms=elapsed_ms)
        logger.error(
            "OpenAI call failed (см. причину ниже): %s%s",
            e,
            (" [%s]" % ctx) if ctx else "",
            exc_info=True,
        )
        return None
