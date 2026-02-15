"""
Валидация ввода для «Проверить действие»: эвристика + дешёвая LLM (gpt-4o-mini).
Цель — не тратить дорогую астрологическую модель на некорректный ввод.
"""

import json
import logging
import re
from typing import Any

from openai import OpenAI

import config

logger = logging.getLogger(__name__)

MODEL = "gpt-4o-mini"
MAX_TOKENS = 120
TEMPERATURE = 0
REQUEST_TIMEOUT = 15

MIN_LEN = 4
MAX_LEN = 160

HEURISTIC_REJECT_PHRASES = (
    "привет",
    "как дела",
    "кто ты",
    "что ты умеешь",
)
LINK_PATTERN = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
ONLY_DIGITS_OR_SYMBOLS = re.compile(r"^[\d\s\W]+$")

SYSTEM_PROMPT = """Ты — классификатор пользовательских намерений.

Твоя задача — определить, является ли текст проверяемым действием.

Проверяемое действие — это конкретное намерение сделать что-то в реальности (например: подписать договор, поговорить с руководителем, купить билет, открыть бизнес).

НЕ является действием:
— эмоция
— абстрактная тема
— философский вопрос
— просьба о прогнозе без действия
— мусорный текст

Верни ТОЛЬКО JSON без пояснений:

{
  "is_action": boolean,
  "action_clean": string,
  "needs_details": boolean,
  "question_to_user": string
}

Правила:
- is_action=false если это не действие.
- action_clean — очищенная краткая формулировка действия.
- needs_details=true если действие есть, но слишком абстрактно (например "поговорить" — неясно с кем).
- question_to_user — один короткий уточняющий вопрос если needs_details=true или is_action=false.
- Никакого текста вне JSON."""

HEURISTIC_FAIL_MESSAGE = (
    "Пожалуйста, укажите конкретное действие. "
    "Например: подписать договор, поговорить с руководителем, купить билет."
)
PARSE_ERROR_FALLBACK = "Пожалуйста, сформулируйте конкретное действие для проверки."
EXAMPLES_SUFFIX = (
    "Пример: подписать договор, подать заявление, поговорить с руководителем."
)


def heuristic_check(text: str) -> tuple[bool, str | None]:
    """
    Локальная проверка без LLM.
    Возвращает (passed, error_message_for_user).
    Если passed=False, error_message_for_user — готовый текст ответа пользователю.
    """
    s = text.strip()
    if len(s) < MIN_LEN:
        return False, HEURISTIC_FAIL_MESSAGE
    if len(s) > MAX_LEN:
        return False, HEURISTIC_FAIL_MESSAGE
    if ONLY_DIGITS_OR_SYMBOLS.match(s):
        return False, HEURISTIC_FAIL_MESSAGE
    if LINK_PATTERN.search(s):
        return False, HEURISTIC_FAIL_MESSAGE
    lower = s.lower()
    for phrase in HEURISTIC_REJECT_PHRASES:
        if phrase in lower:
            return False, HEURISTIC_FAIL_MESSAGE
    # Проверку на глагол (-ть/-ти/-ться) убрали: пользователи вводят «проекта», «отпуск», «в школе»
    # — пусть LLM решает, действие это или нет и запрашивает уточнение
    return True, None


def _call_validation_llm(user_text: str) -> str:
    """Вызов gpt-4o-mini через chat.completions. Возвращает content или поднимает исключение."""
    client = OpenAI(api_key=config.get_openai_api_key())
    user_prompt = f'Текст пользователя:\n"{user_text}"'
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        timeout=REQUEST_TIMEOUT,
    )
    choice = response.choices[0] if response.choices else None
    if not choice or not getattr(choice.message, "content", None):
        raise ValueError("Пустой ответ от LLM")
    return choice.message.content.strip()


def validate_action(user_text: str) -> dict[str, Any]:
    """
    Эвристика + дешёвая LLM-валидация.
    Возвращает dict с ключами: is_action, action_clean, needs_details, question_to_user,
    и опционально parse_error (True при ошибке парсинга JSON или API).
    При неудаче эвристики не вызывается LLM; в этом случае возвращается dict
    с heuristic_fail=True и question_to_user с текстом подсказки.
    """
    passed, err_msg = heuristic_check(user_text)
    if not passed:
        logger.debug("action_validation: heuristic failed for text=%r", user_text[:80])
        return {
            "heuristic_fail": True,
            "is_action": False,
            "action_clean": "",
            "needs_details": False,
            "question_to_user": err_msg or HEURISTIC_FAIL_MESSAGE,
        }

    try:
        raw = _call_validation_llm(user_text)
    except Exception as e:
        logger.warning("action_validation: LLM call failed: %s", e)
        return {
            "parse_error": True,
            "is_action": False,
            "action_clean": "",
            "needs_details": False,
            "question_to_user": PARSE_ERROR_FALLBACK,
        }

    raw_clean = raw.strip()
    if raw_clean.startswith("```"):
        raw_clean = re.sub(r"^```(?:json)?\s*", "", raw_clean)
        raw_clean = re.sub(r"\s*```\s*$", "", raw_clean)
    try:
        data = json.loads(raw_clean)
    except json.JSONDecodeError as e:
        logger.debug("action_validation: JSON decode error: %s, raw=%r", e, raw_clean[:200])
        return {
            "parse_error": True,
            "is_action": False,
            "action_clean": "",
            "needs_details": False,
            "question_to_user": PARSE_ERROR_FALLBACK,
        }

    is_action = data.get("is_action", False)
    action_clean = (data.get("action_clean") or "").strip() or user_text.strip()
    needs_details = data.get("needs_details", False)
    question_to_user = (data.get("question_to_user") or "").strip()

    # Эвристика: одно слово или два коротких — всегда запрашиваем уточнение,
    # иначе ответ «в отпуск» не попадёт в ветку уточнения и уйдёт в меню
    SHORT_ACTION_WORDS = 2
    word_count = len(action_clean.split()) if action_clean else 0
    if is_action and not needs_details and word_count <= SHORT_ACTION_WORDS:
        needs_details = True
        question_to_user = (
            question_to_user
            or "Уточните, пожалуйста: куда, с кем или зачем? (например: в отпуск, с руководителем)"
        )

    result = {
        "is_action": is_action,
        "action_clean": action_clean,
        "needs_details": needs_details,
        "question_to_user": question_to_user or PARSE_ERROR_FALLBACK,
    }
    logger.debug("action_validation: result=%s", result)
    return result
