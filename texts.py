import html
from datetime import datetime, timezone

import db
from config import (
    SETTING_AI_API_KEY,
    SETTING_AI_BASE_URL,
    SETTING_AI_MODEL,
    SETTING_DOWNLOAD_UA,
    SETTING_INTERVAL_MINUTES,
    SETTING_MIN_RATING,
    SETTING_SYSTEM_PROMPT,
    SETTING_TARGET_CHANNEL,
    USER_STATUS_ACTIVE,
    USER_STATUS_BLOCKED,
    USER_STATUS_PENDING,
)


HELP_TEXT = (
    "<b>ContentCurator</b>\n\n"
    "Сборка контента из подключённых источников (RSS)...\n"
    "Перевод и оценка карточек черновиков...\n\n"
    "<b>Разделы меню:</b>\n"
    "<b>База контента</b>\n"
    "<b>Источники</b>\n"
    "<b>Настройки API</b>\n"
    "<b>Настройки ИИ</b>\n\n"
    "В любом пошаговом сценарии жми <code>/cancel</code>."
)

PENDING_TEXT = (
    "<b>Заявка отправлена</b>\n\n"
    "Твой запрос отправлен супер-админу. После одобрения ты получишь уведомление."
)

BLOCKED_TEXT = "<b>Доступ заблокирован.</b>"

RSS_SOURCE_HINT = "Пришли полный URL RSS-фида."

EDITABLE_SETTINGS: list[tuple[str, str]] = [
    (SETTING_AI_API_KEY, "AI API Key"),
    (SETTING_AI_BASE_URL, "AI Base URL"),
    (SETTING_AI_MODEL, "Модель «Сборщик»"),
    (SETTING_TARGET_CHANNEL, "ID целевого канала"),
    (SETTING_INTERVAL_MINUTES, "Интервал парсинга (мин)"),
    (SETTING_MIN_RATING, "Мин. порог рейтинга (1-10)"),
    (SETTING_DOWNLOAD_UA, "User-Agent для загрузки медиа"),
]

SECRET_KEYS = {SETTING_AI_API_KEY}

EDITABLE_PROMPTS: list[tuple[str, str]] = [
    (SETTING_SYSTEM_PROMPT, "Промпт «Сборщик»"),
]

CANCELLED = "Действие отменено."
ACCESS_DENIED = "Доступ закрыт."
MAIN_MENU_LABEL = "Главное меню:"
SOURCES_TITLE = "<b>Источники контента</b>"
NO_POSTS_FOUND = "Посты не найдены."
EMPTY_STATUS = "Здесь пусто. Контента с таким статусом нет."
NO_TOP_CONTENT = "Пока нет оценённого контента."
NO_CHANNEL_SET = "Не задан ID твоего канала.\nЗайди в Настройки API."
POST_NOT_FOUND = "Пост уже удалён или не твой."
SOURCE_NOT_FOUND = "Источник не найден или не твой."
PUBLISH_FAILED = "Ошибка публикации в канал."
PUBLISHED_OK = "Опубликовано в канал!"
PUBLISHED_DONE = "Готово. Пост опубликован."
NO_SOURCES = "Пока нет ни одного источника.\nДобавь первый кнопкой ниже."
SOURCES_LIST_TITLE = "<b>Все источники:</b>"
SOURCES_LIST_FOOTER = "Действия - под каждым источником."
SOURCE_ENABLED = "Включён"
SOURCE_DISABLED = "Выключен"
SOURCE_DELETED = "Удалён."
UNKNOWN_SETTING = "Неизвестная настройка."
UNKNOWN_PROMPT = "Неизвестный промпт."
EXPECT_INTEGER = "Ожидалось целое число. Попробуй ещё раз."
RATING_RANGE = "Значение должно быть в диапазоне 1-10."
MIN_INTERVAL = "Интервал не может быть меньше 1 минуты."
EMPTY_INPUT = "Пустой ввод не допустим. Попробуй ещё раз."
CANT_MODIFY_SUPER = "Не удалось (возможно, это супер-админ)."
NO_PENDING_USERS = "Нет ожидающих заявок."
NO_USERS = "Пользователей нет."
END_OF_LIST = "Конец списка."
SECRET_VALUE_HINT = (
    "\n\nВведи новое значение. Оно хранится в БД и не показывается в чате целиком."
)
BASE_URL_HINT = (
    "\n\nНапример:\n"
    "• Zhipu: <code>https://open.bigmodel.cn/api/paas/v4/</code>\n"
    "• OpenAI: <code>https://api.openai.com/v1</code>\n"
    "• Ollama: <code>http://localhost:11434/v1</code>"
)
SRC_ASK_TITLE = (
    "Теперь пришли <b>короткое название</b> для этого источника "
    "(напр. «r/Python»).\n\nОтправь <code>-</code>, чтобы оставить без названия."
)

POST_ACTION_LABELS: dict[str, tuple[str, str]] = {
    "reject": ("В мусор.", "Пост помечен как мусор."),
    "archive": ("В архив.", "Пост перемещён в архив."),
    "redraft": ("В черновиках.", "Пост снова в очереди модерации."),
}

NOTIFY_TEXTS: dict[str, str] = {
    "approve": ("<b>Доступ одобрен!</b>\n\nТы можешь пользоваться ботом. "
                "Жми /start, чтобы открыть меню."),
    "block": "<b>Доступ к боту заблокирован супер-админом.</b>",
    "unblock": "<b>Доступ восстановлен.</b> Жми /start.",
}

ANSWER_TEXTS: dict[str, str] = {
    "approve": "Одобрен",
    "block": "Заблокирован",
    "unblock": "Разблокирован",
}


def greeting(full_name: str) -> str:
    return f"Привет, <b>{html.escape(full_name)}</b>!\n\n{HELP_TEXT}"


def base_menu(drafts: int, archived: int) -> str:
    return (
        "<b>База контента</b>\n\n"
        f"Черновиков на модерацию: <b>{drafts}</b>\n"
        f"В архиве: <b>{archived}</b>\n\nВыбери, что открыть:"
    )


def users_menu(pending: int, total: int) -> str:
    return (
        "<b>Управление пользователями</b>\n\n"
        f"Заявок на рассмотрение: <b>{pending}</b>\n"
        f"Всего пользователей: <b>{total}</b>"
    )


def settings_overview(entries: list[tuple[str, str]]) -> str:
    lines = ["<b>Текущие значения настроек</b>\n"]
    for label, shown in entries:
        lines.append(f"{label}: <code>{shown}</code>")
    lines.append("\nНажми на кнопку, чтобы изменить значение.")
    return "\n".join(lines)


def prompts_overview(entries: list[tuple[str, str]]) -> str:
    lines = ["<b>Текущие настройки ИИ</b>\n"]
    for label, preview in entries:
        lines.append(f"{label}:\n<i>{preview}</i>\n")
    lines.append("Нажми кнопку ниже, чтобы изменить.")
    return "\n".join(lines)


def format_source(source: dict) -> str:
    flag = "вкл" if source["enabled"] else "выкл"
    title = f" - {html.escape(source['title'])}" if source["title"] else ""
    return (
        f"[{flag}] <b>{html.escape(source['type'].upper())}</b>{title}\n"
        f"<code>{html.escape(source['identifier'])}</code>\nID {source['id']}"
    )


def source_added(identifier: str) -> str:
    return (
        "RSS-источник добавлен.\n"
        f"<code>{html.escape(identifier)}</code>"
    )


def source_add_prompt(hint: str) -> str:
    return f"Добавляем RSS-источник.\n\n{hint}"


def setting_saved(label: str, shown: str) -> str:
    return f"Сохранено.\n<b>{label}</b> = <code>{shown}</code>"


def prompt_saved(label: str) -> str:
    return f"Сохранено.\n<b>{label}</b> обновлён."


def setting_prompt(label: str, hint: str) -> str:
    return f"Изменяем: <b>{label}</b>{hint}\n\nПришли новое значение:"


def prompt_prompt(label: str, hint: str = "") -> str:
    return f"Изменяем: <b>{label}</b>\n\nПришли новый текст промпта (можно в несколько строк)."


def pending_list_title(count: int) -> str:
    return f"<b>Заявки ({count})</b>"


def all_users_title(count: int) -> str:
    return f"<b>Все пользователи ({count})</b>"


def top_list(posts: list[dict]) -> str:
    lines = ["<b>Топ контента по рейтингу ИИ</b>\n"]
    for i, post in enumerate(posts, start=1):
        title = html.escape(
            (post["translated_text"] or post["raw_text"] or "").strip().split("\n")[0][:PREVIEW_LEN]
        )
        lines.append(f"{i}. <b>{post['rating']}/10</b> - {title}  <code>#{post['id']}</code>")
    lines.append("\nОткрой «Черновики», чтобы отмодерировать их.")
    return "\n".join(lines)


def mask(value: str) -> str:
    if not value:
        return "<i>(пусто)</i>"
    if len(value) <= MASK_SHORT_LEN:
        return "****"
    return f"{value[:MASK_HEAD]}{'*' * MASK_MIDDLE}{value[-MASK_TAIL:]}"


def full_name(from_user: dict) -> str:
    return " ".join(
        part for part in (from_user.get("first_name", ""), from_user.get("last_name", "")) if part
    )


def format_user_line(user: dict) -> str:
    badge = {
        USER_STATUS_PENDING: "[ожидает]",
        USER_STATUS_ACTIVE: "[активен]",
        USER_STATUS_BLOCKED: "[заблокирован]",
    }.get(user["status"], "[неизвестен]")
    crown = " [супер-админ]" if user["is_super_admin"] else ""
    username = f"@{html.escape(user['username'])}" if user["username"] else "(без username)"
    return (
        f"{badge} <b>{html.escape(user['full_name'])}</b>{crown}\n"
        f"{username} · ID <code>{user['telegram_id']}</code> · БД #{user['id']}\n"
        f"Статус: <i>{html.escape(user['status'])}</i>"
    )


MAX_CAPTION_LEN = 1024  # Telegram: лимит подписи к медиа
MAX_TEXT_LEN = 4096     # Telegram: лимит текстового сообщения

PREVIEW_LEN = 80
MASK_SHORT_LEN = 8
MASK_HEAD = 5
MASK_MIDDLE = 6
MASK_TAIL = 3


def render_post_caption(
    post: dict, source: dict | None, limit: int = MAX_CAPTION_LEN,
) -> str:
    source_label = (
        f"{html.escape(source['title'] or '(без названия)')} [{html.escape(source['type'])}]"
        if source else "(источник удалён)"
    )

    raw = (post["raw_text"] or "").strip()
    if len(raw) > 500:
        raw = raw[:500] + "…"
    raw_html = html.escape(raw)

    try:
        created = datetime.strptime(post["created_at"], db.DATETIME_ISO)
    except ValueError:
        created = datetime.now(timezone.utc).replace(tzinfo=None)

    def build(body_html: str, include_raw: bool = True) -> str:
        lines = [
            f"<b>Рейтинг:</b> {post['rating']}/10",
            f"<b>Источник:</b> {source_label}",
            f"<b>Собран:</b> {created:%Y-%m-%d %H:%M}",
            "",
            body_html,
        ]
        if include_raw and raw_html:
            lines += ["", "<b>Оригинал:</b>", f"<blockquote>{raw_html}</blockquote>"]
        if post["source_url"]:
            link = html.escape(post["source_url"], quote=True)
            lines += ["", f"Ссылка: <a href=\"{link}\">открыть источник</a>"]
        lines.append(f"\nID <code>#{post['id']}</code>")
        return "\n".join(lines)

    body_raw = (post["translated_text"] or "").strip()

    for include_raw in (True, False):
        max_body = len(body_raw)
        while True:
            if max_body <= 0:
                body_html = "<i>(перевод отсутствует)</i>"
            elif max_body < len(body_raw):
                body_html = html.escape(body_raw[:max_body].rstrip("&") + "…")
            else:
                body_html = html.escape(body_raw)
            caption = build(body_html, include_raw)
            if len(caption) <= limit:
                return caption
            if max_body <= 0:
                break
            max_body //= 2

    # Без тела и без оригинала подпись всегда меньше 1024.
    return build("<i>(перевод отсутствует)</i>", include_raw=False)
