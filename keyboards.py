from config import (
    POST_STATUS_ARCHIVED,
    POST_STATUS_DRAFT,
    USER_STATUS_ACTIVE,
    USER_STATUS_BLOCKED,
    USER_STATUS_PENDING,
)
from texts import EDITABLE_PROMPTS, EDITABLE_SETTINGS


def btn(text: str, callback_value: str) -> dict:
    return {"text": text, "callback_data": callback_value}


def main_menu_kb(is_super_admin: bool = False) -> dict:
    rows = [
        [{"text": "База контента"}],
        [{"text": "Источники"}, {"text": "Настройки API"}],
        [{"text": "Настройки ИИ"}],
    ]
    if is_super_admin:
        rows.append([{"text": "Пользователи"}])
    return {"keyboard": rows, "resize_keyboard": True, "is_persistent": True}


def cancel_kb() -> dict:
    return {"keyboard": [[{"text": "Отмена"}]], "resize_keyboard": True}


def back_to_menu_kb() -> dict:
    return {"inline_keyboard": [[btn("В меню", "back_to_menu")]]}


def post_card_kb(
    post_id: int, status: str = POST_STATUS_DRAFT, offset: int = 0,
    has_prev: bool = False, has_next: bool = False,
) -> dict:
    rows: list[list[dict]] = []
    if status == POST_STATUS_DRAFT:
        rows.append([
            btn("Опубликовать", f"post:approve:{post_id}"),
            btn("В архив", f"post:archive:{post_id}"),
            btn("Удалить", f"post:reject:{post_id}"),
        ])
    elif status == POST_STATUS_ARCHIVED:
        rows.append([
            btn("В черновики", f"post:redraft:{post_id}"),
            btn("Удалить", f"post:reject:{post_id}"),
        ])

    nav = []
    if has_prev:
        nav.append(btn("Пред.", f"pnav:prev:{status}:{offset}"))
    if has_next:
        nav.append(btn("След.", f"pnav:next:{status}:{offset}"))
    if nav:
        rows.append(nav)

    rows.append([btn("В меню", "back_to_menu")])
    return {"inline_keyboard": rows}


def posts_submenu_kb() -> dict:
    return {"inline_keyboard": [
        [btn("Черновики", f"pnav:init:{POST_STATUS_DRAFT}:0")],
        [btn("Топ контента", "list_top")],
        [btn("Архив", f"pnav:init:{POST_STATUS_ARCHIVED}:0")],
        [btn("В меню", "back_to_menu")],
    ]}


def sources_menu_kb() -> dict:
    return {"inline_keyboard": [
        [btn("Список источников", "src:list")],
        [btn("RSS-лента", "src:add")],
        [btn("В меню", "back_to_menu")],
    ]}


def source_actions_kb(source_id: int, enabled: bool) -> dict:
    return {"inline_keyboard": [[
        btn("выкл" if enabled else "вкл", f"src:toggle:{source_id}"),
        btn("Удалить", f"src:del:{source_id}"),
    ]]}


def settings_menu_kb() -> dict:
    return {"inline_keyboard": [
        [btn(label, f"set:{key}")] for key, label in EDITABLE_SETTINGS
    ] + [[btn("В меню", "back_to_menu")]]}


def prompts_menu_kb() -> dict:
    return {"inline_keyboard": [
        [btn(label, f"prm:{key}")] for key, label in EDITABLE_PROMPTS
    ] + [[btn("В меню", "back_to_menu")]]}


def users_menu_kb() -> dict:
    return {"inline_keyboard": [
        [btn("Заявки на доступ", "users_pending")],
        [btn("Все пользователи", "users_all")],
        [btn("В меню", "back_to_menu")],
    ]}


def user_actions_kb(target_user_id: int, status: str, is_super: bool = False) -> dict:
    if is_super:
        return {"inline_keyboard": [[btn("Супер-админ", "noop")]]}

    rows: list[list[dict]] = []
    if status == USER_STATUS_PENDING:
        rows.append([
            btn("Одобрить", f"user:approve:{target_user_id}"),
            btn("Отклонить", f"user:block:{target_user_id}"),
        ])
    elif status == USER_STATUS_ACTIVE:
        rows.append([btn("Заблокировать", f"user:block:{target_user_id}")])
    elif status == USER_STATUS_BLOCKED:
        rows.append([btn("Разблокировать", f"user:unblock:{target_user_id}")])
    rows.append([btn("Назад", "users_all")])
    return {"inline_keyboard": rows}
