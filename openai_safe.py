"""
Обёртка вызовов OpenAI с таймаутом и единой обработкой ошибок.
Защита от зависания запросов: при timeout или ошибке API возвращается None,
обработчик отправляет пользователю сообщение и показывает меню.
"""

import asyncio
import logging
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

# Таймауты (секунды): основная модель дольше, валидация — короче
ASSISTANT_TIMEOUT = 15
VALIDATION_TIMEOUT = 12

MSG_SERVICE_UNAVAILABLE = (
    "⚠️ Сервис временно недоступен. Пожалуйста, попробуйте чуть позже."
)

T = TypeVar("T")


async def safe_openai_call(
    sync_func: Callable[[], T],
    timeout: int = ASSISTANT_TIMEOUT,
) -> T | None:
    """
    Выполняет синхронный вызов OpenAI в executor с таймаутом.
    При TimeoutError, ошибках API или любом исключении логирует и возвращает None.

    :param sync_func: вызываемый без аргументов (например lambda: assistant.send_message_and_get_response(...))
    :param timeout: максимальное время ожидания в секундах
    :return: результат sync_func() или None при ошибке
    """
    try:
        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, sync_func),
            timeout=float(timeout),
        )
        return result
    except asyncio.TimeoutError as e:
        logger.error("OpenAI call timeout after %s s: %s", timeout, e)
        return None
    except Exception as e:
        logger.error("OpenAI call failed: %s", e, exc_info=True)
        return None
