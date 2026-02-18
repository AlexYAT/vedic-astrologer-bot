# Ведический астролог — Telegram-бот

Telegram-бот «Ведический астролог» — персональный советник по ведической астрологии (Джйотиш). Собирает данные рождения и контактную информацию, формирует персонализированные прогнозы через OpenAI Assistants API.

## Технологии

- Python 3.10+
- `python-telegram-bot` 20.x — работа с Telegram
- `openai` — OpenAI Assistants API
- `python-dotenv` — переменные окружения
- SQLite — хранение данных пользователей (таблицы `users` и `user_requests` для аналитики и улучшения продукта)

## Установка

1. Клонируйте репозиторий:
   ```bash
   git clone https://github.com/<username>/vedic-astrologer-bot.git
   cd vedic-astrologer-bot
   ```

2. Создайте виртуальное окружение:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   # source .venv/bin/activate  # Mac/Linux
   ```

3. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```

4. Создайте файл `.env` на основе `.env.example` и заполните ключи:
   ```bash
   copy .env.example .env   # Windows
   # cp .env.example .env   # Mac/Linux
   ```

## Настройка

В `.env` укажите:

- `TELEGRAM_BOT_TOKEN` — токен бота (получить через [@BotFather](https://t.me/BotFather))
- `OPENAI_API_KEY` — API-ключ OpenAI (platform.openai.com)
- `ASSISTANT_ID` — ID ассистента OpenAI (создать в платформе OpenAI, использовать `asst_xxxx...`)

### Создание ассистента OpenAI

1. Перейдите в [platform.openai.com](https://platform.openai.com) → Assistants
2. Создайте ассистента с именем «Vedic Astrologer Assistant»
3. Укажите инструкции (роль ведического астролога)
4. Выберите модель `gpt-4-turbo` или `gpt-4o`
5. Скопируйте ID ассистента в `.env`

## Запуск

```bash
python main.py
```

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие и регистрация / проверка данных |
| `/setdata` | Повторный ввод или изменение данных рождения |
| `/tomorrow` | Прогноз на завтра |
| `/topics` | Выбор темы прогноза (Карьера, Отношения, Здоровье, Финансы, Духовность) |
| `/favorable` | Ближайшие благоприятные дни для начинаний |
| `/contact` | Ввод или обновление контактных данных |
| `/cancel` | Отмена сценария ввода данных |

## База данных

- **users** — пользователи: `telegram_id`, данные рождения (дата, время, место), `thread_id` для OpenAI, флаг `is_pro`.
- **user_requests** — логи запросов к ассистенту: тип (today, tomorrow, check_action, favorable, topic, setdata), текст запроса, успех/ошибка, время ответа. Используется для аналитики и улучшения продукта.

При первом запуске новой версии старая таблица пользователей (если была) переименовывается в `users_legacy`; данные переносятся в новую таблицу при первом обращении пользователя (lazy migration).

## Стратегия проекта

Стратегическая карта развития: [docs/strategy_my_astro_bot_v0_1_feb_2026.mm](docs/strategy_my_astro_bot_v0_1_feb_2026.mm)

## Структура проекта

```
vedic_astrologer_bot/
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
├── config.py
├── db.py
├── assistant.py
├── handlers/
│   ├── __init__.py
│   ├── start.py
│   ├── commands.py
│   └── common.py
└── main.py
```

## Лицензия

MIT
