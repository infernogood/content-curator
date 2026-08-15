# ContentCurator (easy)

Упрощённая версия контент-менеджера для Telegram: без asyncio, без aiogram,
без Telethon (Telegram-источники убраны). Только **Python + `sqlite3` (stdlib)
+ `requests` + `feedparser`**.

Бот собирает контент из RSS-источников, переводит и
оценивает его через LLM (любой OpenAI-совместимый API: Zhipu/GLM, OpenAI,
Ollama, vLLM) и присылает карточки-черновики на модерацию.

## Структура

```
ContentCurator/
├── main.py          # точка входа: init_db + цикл bot.run()
├── config.py        # пути, .env, дефолты Settings
├── db.py            # SQLite: все запросы (users/settings/sources/posts)
├── bot.py           # бот на requests: long polling, клавиатуры, обработчики
├── services.py      # коллекторы (RSS) + LLM + пайплайн
├── .env.example
└── requirements.txt
```

## Установка и запуск

```bash
python -m venv venv
venv\Scripts\activate          # Windows   (Linux/Mac: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env         # заполнить BOT_TOKEN и ADMIN_IDS
python main.py
```

Остановка - `Ctrl+C`.

## Первый запуск

1. Напиши боту `/start` - супер-админ из `ADMIN_IDS` получит доступ сразу,
   обычные юзеры попадут в «Заявки» (меню Пользователи).
2. В меню **Настройки API** укажи `ai_api_key` (и при необходимости
   `ai_base_url`, модели, `target_channel_id`, интервалы).
3. В меню **Источники** добавь RSS-источники.
4. Коллектор сам тикает каждую минуту и собирает «дозревшие» источники.

## Модель данных (multi-user)

* `users` - юзеры бота: `pending` / `active` / `blocked`.
* `settings` - пары ключ-значение; `owner_id=NULL` = системный дефолт,
  `owner_id=<id>` = персональное значение (приоритетнее).
* `sources` - источники юзера: `rss`.
* `posts` - карточки контента юзера: `draft` / `approved` / `rejected` / `archived`.

Изоляция данных: все операции над источниками/постами фильтруются по
`owner_id`, дедуп - уникальный `dedup_hash` в пределах юзера.

## Зачем без async?

Минимальный порог входа: один язык, один файл на слой, никаких event-loop,
middleware и DI. Цена - бот не обрабатывает сообщения, пока идёт долгий
вызов LLM (10-30 сек). Для личного бота на 1-5 юзеров это нормально.