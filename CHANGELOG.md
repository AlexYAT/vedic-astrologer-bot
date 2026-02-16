# Changelog

## [0.3.0] — 2026-02-15

### Added

- Новая схема БД: две таблицы — **users** (id, telegram_id, birth_*, thread_id, created_at, is_pro) и **user_requests** (логи запросов по типам: today, tomorrow, check_action, favorable, topic, setdata).
- Логирование каждого запроса к ассистенту: тип, опциональный текст, успех/ошибка (success), время ответа (response_time_ms) для аналитики и улучшения продукта.
- Мягкая миграция: при первом запуске старая таблица `users` переименовывается в `users_legacy`; данные переносятся в новую таблицу при первом обращении пользователя (lazy migration). Старые таблицы не удаляются.

### Changed

- Инициализация БД создаёт новые таблицы и индекс `idx_user_requests_user_id_created_at`.
- API слоя db: `get_or_create_user(telegram_id)`, `update_user_birth_data`, `get_user_birth_data`, `log_user_request`; прежние вызовы (`get_user`, `user_has_full_data`, `create_user`, `save_user_data`, `update_user`) сохранены для совместимости.

---

## [0.2.0]

- Централизованное хранение версии в `version.py`, логирование версии при старте.
