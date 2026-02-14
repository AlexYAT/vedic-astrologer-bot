# Ведический астролог — Telegram-бот

Telegram-бот «Ведический астролог» — персональный советник по ведической астрологии (Джйотиш). Собирает данные рождения и контактную информацию, формирует персонализированные прогнозы через OpenAI Assistants API.

## Технологии

- Python 3.10+
- `python-telegram-bot` 20.x — работа с Telegram
- `openai` — OpenAI Assistants API
- `python-dotenv` — переменные окружения
- SQLite — хранение данных пользователей

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
