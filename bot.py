import html
import json
import logging
import os
import time
from typing import Any, Callable

import requests

import db
import keyboards
import services
import texts
from config import (
    ADMIN_IDS,
    MEDIA_TYPE_ANIMATION,
    MEDIA_TYPE_DOCUMENT,
    MEDIA_TYPE_PHOTO,
    MEDIA_TYPE_VIDEO,
    POST_STATUS_APPROVED,
    POST_STATUS_ARCHIVED,
    POST_STATUS_DRAFT,
    POST_STATUS_REJECTED,
    SETTING_AI_BASE_URL,
    SETTING_INTERVAL_MINUTES,
    SETTING_MIN_RATING,
    SETTING_TARGET_CHANNEL,
    SOURCE_TYPE_RSS,
    USER_STATUS_ACTIVE,
    USER_STATUS_BLOCKED,
    USER_STATUS_PENDING,
)

log = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org/bot{token}/{method}"
CALLBACK_ALERT_MAX_LEN = 200


class Telegram:

    def __init__(self, token: str) -> None:
        if not token:
            raise RuntimeError("BOT_TOKEN не задан. Укажи его в .env")
        self.token = token

    def _url(self, method: str) -> str:
        return API_BASE.format(token=self.token, method=method)

    def _request(
        self, method: str, body: dict, files: dict | None = None, timeout: int = 60,
    ) -> dict | None:
        try:
            if files:
                multipart_data = {
                    key: (json.dumps(value) if isinstance(value, dict) else value)
                    for key, value in body.items()
                }
                resp = requests.post(self._url(method), data=multipart_data, files=files, timeout=timeout)
            else:
                resp = requests.post(self._url(method), json=body, timeout=timeout)
        except requests.RequestException as exc:
            log.warning("API %s: сетевой сбой: %s", method, exc)
            return None
        return self._parse(method, resp)

    @staticmethod
    def _parse(method: str, resp: requests.Response) -> dict | None:
        if resp.status_code != 200:
            log.warning("API %s: HTTP %s: %s", method, resp.status_code, resp.text[:200])
            return None
        try:
            body = resp.json()
        except ValueError:
            log.warning("API %s: не-JSON ответ: %s", method, resp.text[:200])
            return None
        if not body.get("ok"):
            log.warning("API %s: ok=False: %s", method, body.get("description"))
            return None
        return body.get("result")

    def get_me(self) -> dict | None:
        return self._request("getMe", {})

    def get_updates(self, offset: int) -> list[dict]:
        body = {
            "offset": offset,
            "timeout": 25,
            "allowed_updates": ["message", "callback_query"],
        }
        updates = self._request("getUpdates", body, timeout=60)
        return updates or []

    def send_message(
        self, chat_id, text: str, reply_markup: dict | None = None,
    ) -> dict | None:
        body: dict[str, Any] = {
            "chat_id": chat_id, "text": text, "parse_mode": "HTML",
        }
        if reply_markup is not None:
            body["reply_markup"] = reply_markup
        return self._request("sendMessage", body)

    def answer_callback(self, cb_id: str, text: str | None = None, show_alert: bool = False) -> None:
        body: dict[str, Any] = {"callback_query_id": cb_id}
        if text:
            body["text"] = text[:CALLBACK_ALERT_MAX_LEN]
        if show_alert:
            body["show_alert"] = True
        self._request("answerCallbackQuery", body)

    def edit_message_text(
        self, chat_id, message_id: int, text: str, reply_markup: dict | None = None,
    ) -> None:
        body = {
            "chat_id": chat_id, "message_id": message_id,
            "text": text, "parse_mode": "HTML",
        }
        if reply_markup is not None:
            body["reply_markup"] = reply_markup
        self._request("editMessageText", body)

    def edit_reply_markup(self, chat_id, message_id: int, reply_markup: dict | None = None) -> None:
        body = {"chat_id": chat_id, "message_id": message_id}
        if reply_markup is not None:
            body["reply_markup"] = reply_markup
        self._request("editMessageReplyMarkup", body)

    def delete_message(self, chat_id, message_id: int) -> None:
        self._request("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

    _MEDIA = {
        MEDIA_TYPE_PHOTO: ("sendPhoto", MEDIA_TYPE_PHOTO),
        MEDIA_TYPE_VIDEO: ("sendVideo", MEDIA_TYPE_VIDEO),
        MEDIA_TYPE_ANIMATION: ("sendAnimation", MEDIA_TYPE_ANIMATION),
        MEDIA_TYPE_DOCUMENT: ("sendDocument", MEDIA_TYPE_DOCUMENT),
    }

    MEDIA_TYPES = frozenset(_MEDIA)

    def send_media(
        self, chat_id, media_path_or_id, media_type: str, caption: str | None = None,
        reply_markup: dict | None = None,
    ) -> dict | None:
        media_spec = self._MEDIA.get(media_type)
        if media_spec is None:
            return self.send_message(chat_id, caption or "", reply_markup)
        method, field = media_spec

        media_ref = str(media_path_or_id) if media_path_or_id else ""

        body: dict[str, Any] = {"chat_id": chat_id, "parse_mode": "HTML", "caption": caption}
        if reply_markup is not None:
            body["reply_markup"] = reply_markup

        if media_ref and os.path.exists(media_ref):
            with open(media_ref, "rb") as fh:
                return self._request(method, body, files={field: fh}, timeout=120)
        body[field] = media_ref
        return self._request(method, body)

    def send_new_post(
        self, chat_id, caption: str, media_path_or_id, reply_markup: dict | None = None,
    ) -> str | None:
        if not media_path_or_id:
            self.send_message(chat_id, caption, reply_markup)
            return None

        media_type = services.classify_media(media_path_or_id)
        sent_message = self.send_media(chat_id, media_path_or_id, media_type, caption, reply_markup)
        if not sent_message:
            return None
        if media_type == MEDIA_TYPE_PHOTO:
            photo = sent_message.get("photo") or []
            return photo[-1].get("file_id") if photo else None
        entity = sent_message.get(media_type)
        if isinstance(entity, dict):
            return entity.get("file_id")
        return None


def _is_active(user: dict | None) -> bool:
    return bool(user and user["status"] == USER_STATUS_ACTIVE)


def _resolve_user(tg_user: dict) -> tuple[dict, bool]:
    is_super = tg_user["id"] in ADMIN_IDS
    user = db.upsert_user(
        tg_user["id"], tg_user.get("username", "") or "", texts.full_name(tg_user), is_super,
    )
    return user, is_super


def _has_media(post: dict) -> bool:
    return bool(post["media_file_id"] and post["media_type"] in Telegram.MEDIA_TYPES)


def _send_post_card(tg: Telegram, chat_id: int, post: dict, status: str, offset: int, total: int) -> None:
    source = db.get_source(post["owner_id"], post["source_id"]) if post["source_id"] else None
    limit = texts.MAX_CAPTION_LEN if _has_media(post) else texts.MAX_TEXT_LEN
    caption = texts.render_post_caption(post, source, limit)
    kb = keyboards.post_card_kb(
        post["id"], status=status, offset=offset,
        has_prev=offset > 0, has_next=offset < total - 1,
    )
    if _has_media(post):
        tg.send_media(chat_id, post["media_file_id"], post["media_type"], caption, kb)
    else:
        tg.send_message(chat_id, caption, kb)


def _open_kv_editor(
    tg: Telegram, chat: int, user: dict,
    pairs: list[tuple[str, str]],
    render_fn: Callable[[list[tuple[str, str]]], str],
    kb_fn: Callable[[], dict],
    preview_len: int | None = None,
) -> None:
    rows = []
    for key, label in pairs:
        value = db.get_effective(user["id"], key, "")
        if preview_len is not None and len(value) > preview_len:
            value = value[:preview_len] + "…"
        if key in texts.SECRET_KEYS:
            shown = html.escape(texts.mask(value))
        elif value:
            shown = html.escape(value)
        else:
            shown = "<i>(пусто)</i>"
        rows.append((label, shown))
    tg.send_message(chat, render_fn(rows), kb_fn())


def _open_settings(tg: Telegram, chat: int, user: dict) -> None:
    _open_kv_editor(
        tg, chat, user,
        texts.EDITABLE_SETTINGS, texts.settings_overview, keyboards.settings_menu_kb,
    )


def _open_prompts(tg: Telegram, chat: int, user: dict) -> None:
    _open_kv_editor(
        tg, chat, user,
        texts.EDITABLE_PROMPTS, texts.prompts_overview, keyboards.prompts_menu_kb,
        preview_len=texts.PREVIEW_LEN,
    )


def _open_content_base(tg: Telegram, chat: int, user: dict) -> None:
    drafts = db.count_by_status(user["id"], POST_STATUS_DRAFT)
    archived = db.count_by_status(user["id"], POST_STATUS_ARCHIVED)
    tg.send_message(chat, texts.base_menu(drafts, archived), keyboards.posts_submenu_kb())


def _open_sources(tg: Telegram, chat: int, user: dict) -> None:
    tg.send_message(chat, texts.SOURCES_TITLE, keyboards.sources_menu_kb())


def _open_users(tg: Telegram, chat: int, user: dict) -> None:
    pending = len(db.list_pending_users())
    total = db.count_users()
    tg.send_message(chat, texts.users_menu(pending, total), keyboards.users_menu_kb())


MENU_HANDLERS: dict[str, Callable[[Telegram, int, dict], None]] = {
    "База контента": _open_content_base,
    "Источники": _open_sources,
    "Настройки API": _open_settings,
    "Настройки ИИ": _open_prompts,
}


def handle_update(tg: Telegram, update: dict, fsms: dict) -> None:
    if "message" in update:
        handle_message(tg, update["message"], fsms)
    elif "callback_query" in update:
        handle_callback(tg, update["callback_query"], fsms)


def handle_message(tg: Telegram, msg: dict, fsms: dict) -> None:
    tg_user = msg.get("from")
    if not tg_user:
        return
    chat = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()

    user, _ = _resolve_user(tg_user)
    tg_id = user["telegram_id"]

    if text == "/start":
        fsms.pop(tg_id, None)
        if user["status"] == USER_STATUS_PENDING:
            tg.send_message(chat, texts.PENDING_TEXT)
            return
        if user["status"] == USER_STATUS_BLOCKED:
            tg.send_message(chat, texts.BLOCKED_TEXT)
            return
        tg.send_message(
            chat, texts.greeting(user["full_name"]),
            keyboards.main_menu_kb(user["is_super_admin"]),
        )
        return

    if not _is_active(user):
        return

    fsm = fsms.get(tg_id)
    if fsm:
        finished = _handle_fsm_message(tg, msg, chat, user, fsm, text)
        if finished:
            fsms.pop(tg_id, None)
        return

    if text == "/help":
        tg.send_message(chat, texts.HELP_TEXT)
        return
    if text in ("/cancel", "Отмена"):
        tg.send_message(chat, texts.CANCELLED, keyboards.main_menu_kb(user["is_super_admin"]))
        return

    handler = MENU_HANDLERS.get(text)
    if handler is not None:
        handler(tg, chat, user)
        return
    if text == "Пользователи" and user["is_super_admin"]:
        _open_users(tg, chat, user)


def _handle_fsm_message(
    tg: Telegram, msg: dict, chat: int, user: dict, fsm: dict, text: str,
) -> bool:
    if text == "Отмена":
        menu = fsm.get("back", "main")
        if menu == "sources":
            kb = keyboards.sources_menu_kb()
        elif menu == "settings":
            kb = keyboards.settings_menu_kb()
        elif menu == "prompts":
            kb = keyboards.prompts_menu_kb()
        else:
            kb = keyboards.main_menu_kb(user["is_super_admin"])
        tg.send_message(chat, texts.CANCELLED, kb)
        return True

    state = fsm.get("state")
    state_data = fsm.get("state_data", {})

    if state == "src_wait":
        if state_data.get("step") != "title":
            state_data["identifier"] = text
            state_data["step"] = "title"
            fsm["state_data"] = state_data
            tg.send_message(chat, texts.SRC_ASK_TITLE, keyboards.cancel_kb())
            return False
        db.add_source(
            user["id"], SOURCE_TYPE_RSS, state_data["identifier"], "" if text == "-" else text,
        )
        tg.send_message(
            chat,
            texts.source_added(state_data["identifier"]),
            keyboards.sources_menu_kb(),
        )
        return True

    if state == "set_wait":
        key, label = state_data["key"], state_data["label"]
        if key in {SETTING_INTERVAL_MINUTES, SETTING_MIN_RATING}:
            if not text.isdigit():
                tg.send_message(chat, texts.EXPECT_INTEGER)
                return False
            value = int(text)
            if key == SETTING_MIN_RATING and not (1 <= value <= 10):
                tg.send_message(chat, texts.RATING_RANGE)
                return False
            if key == SETTING_INTERVAL_MINUTES and value < 1:
                tg.send_message(chat, texts.MIN_INTERVAL)
                return False

        db.set_setting(user["id"], key, text, label)
        shown = html.escape(texts.mask(text)) if key in texts.SECRET_KEYS else html.escape(text)
        tg.send_message(chat, texts.setting_saved(label, shown), keyboards.settings_menu_kb())
        return True

    if state == "prm_wait":
        if not text:
            tg.send_message(chat, texts.EMPTY_INPUT)
            return False
        key, label = state_data["key"], state_data["label"]
        db.set_setting(user["id"], key, text, label)
        tg.send_message(chat, texts.prompt_saved(label), keyboards.prompts_menu_kb())
        return True

    return True


def handle_callback(tg: Telegram, cb: dict, fsms: dict) -> None:
    tg_user = cb.get("from")
    if not tg_user:
        return
    chat = cb["message"]["chat"]["id"]
    message_id = cb["message"]["message_id"]
    cb_id = cb["id"]
    callback_value = cb.get("data", "")

    user, _ = _resolve_user(tg_user)

    if not _is_active(user):
        tg.answer_callback(cb_id, texts.ACCESS_DENIED, show_alert=True)
        return

    if callback_value == "noop":
        tg.answer_callback(cb_id)
        return

    if callback_value == "back_to_menu":
        fsms.pop(user["telegram_id"], None)
        tg.answer_callback(cb_id)
        tg.send_message(chat, texts.MAIN_MENU_LABEL, keyboards.main_menu_kb(user["is_super_admin"]))
        tg.delete_message(chat, message_id)
        return

    if callback_value == "list_top":
        top = db.list_best(user["id"], limit=10)
        if not top:
            tg.send_message(chat, texts.NO_TOP_CONTENT, keyboards.back_to_menu_kb())
        else:
            tg.send_message(chat, texts.top_list(top), keyboards.back_to_menu_kb())
        tg.delete_message(chat, message_id)
        tg.answer_callback(cb_id)
        return

    segments = callback_value.split(":")
    handler = CALLBACK_HANDLERS.get(segments[0])
    if handler is not None:
        handler(tg, chat, message_id, cb_id, user, segments, fsms)
        return

    if not user["is_super_admin"]:
        tg.answer_callback(cb_id, texts.ACCESS_DENIED, show_alert=True)
        return

    if callback_value in ("users_pending", "users_all"):
        _render_users(tg, chat, cb_id, pending_only=(callback_value == "users_pending"))
        return

    tg.answer_callback(cb_id)


def _handle_pnav(
    tg: Telegram, chat: int, message_id: int, cb_id: str,
    user: dict, segments: list[str], fsms: dict,
) -> None:
    # Формат callback: pnav:<next|prev|init>:<status>:<offset>
    direction = segments[1]
    status = segments[2]
    offset = services.parse_int(segments[3])

    if direction == "next":
        offset += 1
    elif direction == "prev":
        offset = max(offset - 1, 0)

    total = db.count_by_status(user["id"], status)
    if total == 0:
        tg.answer_callback(cb_id)
        tg.send_message(chat, texts.EMPTY_STATUS, keyboards.back_to_menu_kb())
        tg.delete_message(chat, message_id)
        return

    offset = min(offset, total - 1)
    posts = db.list_by_status(user["id"], status, limit=1, offset=offset)
    if not posts:
        tg.answer_callback(cb_id, texts.NO_POSTS_FOUND, show_alert=True)
        return
    _send_post_card(tg, chat, posts[0], status, offset, total)
    tg.delete_message(chat, message_id)
    tg.answer_callback(cb_id)


def _publish_post(
    tg: Telegram, chat: int, message_id: int, cb_id: str, user: dict, post_id: int,
) -> None:
    channel_id = db.get_effective(user["id"], SETTING_TARGET_CHANNEL, "").strip()
    if not channel_id:
        tg.answer_callback(cb_id, texts.NO_CHANNEL_SET, show_alert=True)
        return

    post = db.get_post(user["id"], post_id)
    if post is None:
        tg.answer_callback(cb_id, texts.POST_NOT_FOUND, show_alert=True)
        return

    text = post["translated_text"] or post["raw_text"] or ""
    has_media = _has_media(post)
    limit = texts.MAX_CAPTION_LEN if has_media else texts.MAX_TEXT_LEN
    text = texts.truncate(text, limit)
    if has_media:
        published = tg.send_media(
            channel_id, post["media_file_id"], post["media_type"], html.escape(text),
        ) is not None
    else:
        published = tg.send_message(channel_id, html.escape(text)) is not None

    if not published:
        tg.answer_callback(cb_id, texts.PUBLISH_FAILED, show_alert=True)
        return

    db.update_post_status(user["id"], post_id, POST_STATUS_APPROVED, set_published_at=True)
    tg.answer_callback(cb_id, texts.PUBLISHED_OK)
    tg.edit_reply_markup(chat, message_id, None)
    tg.send_message(chat, texts.PUBLISHED_DONE, keyboards.back_to_menu_kb())


def _handle_post(
    tg: Telegram, chat: int, message_id: int, cb_id: str,
    user: dict, segments: list[str], fsms: dict,
) -> None:
    action = segments[1]
    post_id = services.parse_int(segments[2])

    if action == "approve":
        _publish_post(tg, chat, message_id, cb_id, user, post_id)
        return

    new_status = {
        "reject": POST_STATUS_REJECTED,
        "archive": POST_STATUS_ARCHIVED,
        "redraft": POST_STATUS_DRAFT,
    }.get(action)
    if new_status is not None:
        db.update_post_status(user["id"], post_id, new_status)
        answer, message = texts.POST_ACTION_LABELS[action]
        tg.answer_callback(cb_id, answer)
        tg.edit_reply_markup(chat, message_id, None)
        tg.send_message(chat, message, keyboards.back_to_menu_kb())
        return
    tg.answer_callback(cb_id)


def _render_sources(tg: Telegram, chat: int, user: dict) -> None:
    sources = db.list_sources(user["id"])
    if not sources:
        tg.send_message(chat, texts.NO_SOURCES, keyboards.sources_menu_kb())
        return
    tg.send_message(chat, texts.SOURCES_LIST_TITLE)
    for source in sources:
        tg.send_message(
            chat, texts.format_source(source),
            keyboards.source_actions_kb(source["id"], bool(source["enabled"])),
        )
    tg.send_message(chat, texts.SOURCES_LIST_FOOTER, keyboards.sources_menu_kb())


def _handle_src(
    tg: Telegram, chat: int, message_id: int, cb_id: str,
    user: dict, segments: list[str], fsms: dict,
) -> None:
    if segments[1] == "list":
        _render_sources(tg, chat, user)
        tg.answer_callback(cb_id)
        return

    if segments[1] == "add":
        fsms[user["telegram_id"]] = {
            "state": "src_wait",
            "state_data": {"step": "id"},
            "back": "sources",
        }
        tg.answer_callback(cb_id)
        tg.send_message(chat, texts.source_add_prompt(texts.RSS_SOURCE_HINT), keyboards.cancel_kb())
        return

    if segments[1] in ("toggle", "del"):
        source_id = services.parse_int(segments[2])
        if segments[1] == "toggle":
            new_state = db.toggle_source(user["id"], source_id)
            if new_state is None:
                tg.answer_callback(cb_id, texts.SOURCE_NOT_FOUND, show_alert=True)
                return
            tg.answer_callback(cb_id, texts.SOURCE_ENABLED if new_state else texts.SOURCE_DISABLED)
        else:
            if not db.delete_source(user["id"], source_id):
                tg.answer_callback(cb_id, texts.SOURCE_NOT_FOUND, show_alert=True)
                return
            tg.answer_callback(cb_id, texts.SOURCE_DELETED)
        _render_sources(tg, chat, user)
        return


def _kv_setting_hint(key: str) -> str:
    if key in texts.SECRET_KEYS:
        return texts.SECRET_VALUE_HINT
    if key == SETTING_AI_BASE_URL:
        return texts.BASE_URL_HINT
    return ""


KV_CALLBACKS: dict[str, dict[str, Any]] = {
    "set": {
        "pairs": texts.EDITABLE_SETTINGS,
        "state": "set_wait",
        "back": "settings",
        "unknown": texts.UNKNOWN_SETTING,
        "prompt": texts.setting_prompt,
        "hint": _kv_setting_hint,
    },
    "prm": {
        "pairs": texts.EDITABLE_PROMPTS,
        "state": "prm_wait",
        "back": "prompts",
        "unknown": texts.UNKNOWN_PROMPT,
        "prompt": texts.prompt_prompt,
        "hint": None,
    },
}


def _handle_kv_edit(
    tg: Telegram, chat: int, message_id: int, cb_id: str,
    user: dict, segments: list[str], fsms: dict,
) -> None:
    editor = KV_CALLBACKS.get(segments[0])
    if editor is None:
        tg.answer_callback(cb_id)
        return

    key = segments[1]
    label = dict(editor["pairs"]).get(key)
    if label is None:
        tg.answer_callback(cb_id, editor["unknown"], show_alert=True)
        return

    hint_builder = editor["hint"]
    hint = hint_builder(key) if hint_builder else ""

    fsms[user["telegram_id"]] = {
        "state": editor["state"],
        "state_data": {"key": key, "label": label},
        "back": editor["back"],
    }
    tg.answer_callback(cb_id)
    tg.send_message(chat, editor["prompt"](label, hint), keyboards.cancel_kb())


def _handle_user(
    tg: Telegram, chat: int, message_id: int, cb_id: str,
    user: dict, segments: list[str], fsms: dict,
) -> None:
    if not user["is_super_admin"]:
        tg.answer_callback(cb_id, texts.ACCESS_DENIED, show_alert=True)
        return

    action = segments[1]
    target_id = services.parse_int(segments[2])

    target_status = {
        "approve": USER_STATUS_ACTIVE,
        "block": USER_STATUS_BLOCKED,
        "unblock": USER_STATUS_ACTIVE,
    }.get(action, USER_STATUS_ACTIVE)
    ok = db.set_user_status(target_id, target_status)
    notify_text = texts.NOTIFY_TEXTS.get(action)
    answer = texts.ANSWER_TEXTS.get(action)

    if not ok:
        tg.answer_callback(cb_id, texts.CANT_MODIFY_SUPER, show_alert=True)
        return

    target_user = db.get_user(target_id)
    if notify_text and target_user is not None:
        tg.send_message(
            target_user["telegram_id"], notify_text,
            keyboards.main_menu_kb(target_user["is_super_admin"]),
        )

    tg.answer_callback(cb_id, answer)
    if target_user is not None and answer:
        tg.edit_message_text(
            chat, message_id,
            f"{texts.format_user_line(target_user)}\n\n-> <b>{answer.upper()}</b>",
        )


CALLBACK_HANDLERS: dict[str, Callable] = {
    "pnav": _handle_pnav,
    "post": _handle_post,
    "src": _handle_src,
    "set": _handle_kv_edit,
    "prm": _handle_kv_edit,
    "user": _handle_user,
}


def _render_users(tg: Telegram, chat: int, cb_id: str, pending_only: bool) -> None:
    users = db.list_pending_users() if pending_only else db.list_users()
    if not users:
        tg.send_message(
            chat,
            texts.NO_PENDING_USERS if pending_only else texts.NO_USERS,
            keyboards.users_menu_kb(),
        )
    else:
        title = (
            texts.pending_list_title(len(users))
            if pending_only else texts.all_users_title(len(users))
        )
        tg.send_message(chat, title)
        for listed_user in users:
            tg.send_message(
                chat, texts.format_user_line(listed_user),
                keyboards.user_actions_kb(
                    listed_user["id"], listed_user["status"], listed_user["is_super_admin"],
                ),
            )
        tg.send_message(chat, texts.END_OF_LIST, keyboards.users_menu_kb())
    tg.answer_callback(cb_id)


def run(tg: Telegram, collector_every: int = 60) -> None:
    me = tg.get_me() or {}
    log.info("Бот @%s (id=%s) готов к работе.", me.get("username"), me.get("id"))

    fsms: dict = {}
    offset = 0
    last_collect = 0.0

    while True:
        try:
            if time.time() - last_collect >= collector_every:
                last_collect = time.time()
                try:
                    services.run_collection(tg)
                except Exception:
                    log.exception("Сбой цикла коллектора")

            updates = tg.get_updates(offset)
            for update in updates:
                offset = max(offset, update["update_id"] + 1)
                try:
                    handle_update(tg, update, fsms)
                except Exception:
                    log.exception("Сбой обработки update")

        except KeyboardInterrupt:
            raise
        except Exception:
            log.exception("Сбой главного цикла")
            time.sleep(5)
