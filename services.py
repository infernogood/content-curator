import html
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Protocol

import feedparser
import requests

import db
import keyboards
import texts
from config import (
    DEFAULT_DOWNLOAD_UA,
    MEDIA_TYPE_ANIMATION,
    MEDIA_TYPE_DOCUMENT,
    MEDIA_TYPE_PHOTO,
    MEDIA_TYPE_TEXT,
    MEDIA_TYPE_VIDEO,
    POST_STATUS_DRAFT,
    SETTING_AI_API_KEY,
    SETTING_AI_BASE_URL,
    SETTING_AI_MODEL,
    SETTING_DOWNLOAD_UA,
    SETTING_INTERVAL_MINUTES,
    SETTING_MIN_RATING,
    SETTING_SYSTEM_PROMPT,
    SOURCE_TYPE_RSS,
    TMP_DIR,
)

log = logging.getLogger(__name__)

LLM_RAW_TEXT_LIMIT = 8000
LLM_SUMMARY_LIMIT = 2000
CAPTION_OVERHEAD = 100  # запас на шапку, разделители и ID внутри caption


class MediaSender(Protocol):
    """Клиент Telegram, умеющий отправлять пост с медиа и возвращать file_id."""

    def send_new_post(
        self, chat_id, caption: str, media_path_or_id, reply_markup: dict | None = None,
    ) -> str | None:
        ...


MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
    "image/webp": ".webp", "image/gif": ".gif", "video/mp4": ".mp4",
    "video/quicktime": ".mov",
}

_IMG_RE = re.compile(r'<img[^>]+(?:src|data-src)=["\']([^"\'>\s]+)["\']', re.IGNORECASE)

MAX_DOWNLOAD_BYTES: int = 20 * 1024 * 1024


def _guess_extension(content_type: str, url: str) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in MIME_TO_EXT:
        return MIME_TO_EXT[ct]
    path = url.split("?")[0].split("#")[0]
    if "." in path.rsplit("/", 1)[-1]:
        return "." + path.rsplit(".", 1)[-1].lower()
    return ".bin"


def download(url: str, *, headers: dict[str, str] | None = None) -> Path | None:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    file_path = TMP_DIR / f"{uuid.uuid4().hex}.bin"

    # Часть CDN отдаёт 403 без браузерного User-Agent, поэтому он всегда проставляется.
    request_headers = {"User-Agent": DEFAULT_DOWNLOAD_UA}
    if headers:
        request_headers.update(headers)

    try:
        with requests.get(url, headers=request_headers, timeout=(10, 30), stream=True) as resp:
            if resp.status_code != 200:
                log.warning("Скачивание %s: HTTP %s", url, resp.status_code)
                return None

            ext = _guess_extension(resp.headers.get("Content-Type", ""), url)
            file_path = file_path.with_suffix(ext)

            written = 0
            limit_exceeded = False
            with open(file_path, "wb") as f:
                for chunk in resp.iter_content(64 * 1024):
                    if written + len(chunk) > MAX_DOWNLOAD_BYTES:
                        limit_exceeded = True
                        break
                    f.write(chunk)
                    written += len(chunk)
            if limit_exceeded:
                cleanup(file_path)
                log.warning("Скачивание %s: превышен лимит %d байт", url, MAX_DOWNLOAD_BYTES)
                return None
    except (requests.RequestException, TimeoutError, OSError) as exc:
        log.warning("Сбой скачивания %s: %s", url, exc)
        cleanup(file_path)
        return None

    return file_path


def cleanup(path: Path | str | None) -> None:
    if path is None:
        return
    try:
        os.remove(path)
    except (FileNotFoundError, OSError):
        pass


def classify_media(path: Path | str) -> str:
    ext = Path(path).suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp"}:
        return MEDIA_TYPE_PHOTO
    if ext == ".gif":
        return MEDIA_TYPE_ANIMATION
    if ext in {".mp4", ".mov"}:
        return MEDIA_TYPE_VIDEO
    return MEDIA_TYPE_DOCUMENT


def _llm_chat(
    base_url: str, api_key: str, model: str,
    system_prompt: str, user_content: str, temperature: float,
) -> str:
    """Один запрос chat/completions. Возвращает текст ответа или ""."""
    if not api_key:
        log.warning("LLM %s: не задан ai_api_key - пустой ответ", model)
        return ""

    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
    except requests.RequestException as exc:
        log.warning("LLM %s: сетевой сбой: %s", model, exc)
        return ""
    if resp.status_code != 200:
        log.warning("LLM %s: HTTP %s: %s", model, resp.status_code, resp.text[:200])
        return ""

    try:
        return (resp.json()["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, ValueError) as exc:
        log.warning("LLM %s: неожиданный ответ: %s", model, exc)
        return ""


def analyze(user_id: int, raw_text: str) -> tuple[int, str]:
    if not raw_text or not raw_text.strip():
        return 0, ""

    base_url = db.get_effective(user_id, SETTING_AI_BASE_URL, "https://open.bigmodel.cn/api/paas/v4/")
    api_key = db.get_effective(user_id, SETTING_AI_API_KEY, "")
    model = db.get_effective(user_id, SETTING_AI_MODEL, "glm-4-flash")
    prompt = db.get_effective(user_id, SETTING_SYSTEM_PROMPT, "")

    content = _llm_chat(base_url, api_key, model, prompt, raw_text[:LLM_RAW_TEXT_LIMIT], temperature=0.3)
    return _parse_analysis(content)


def _try_parse_json(text: str) -> dict | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[len("json"):].lstrip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(cleaned[start:end + 1], strict=False)
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        return None


def parse_int(value, fallback: int = 0) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        return fallback


def _parse_db_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, db.DATETIME_ISO)
    except ValueError:
        return None


def _parse_analysis(content: str) -> tuple[int, str]:
    if not content:
        return 0, ""

    parsed = _try_parse_json(content)
    if parsed is not None:
        rating = parse_int(parsed.get("rating"), fallback=0)
        rating = max(0, min(rating, 10))
        summary = str(parsed.get("summary") or "").strip()[:LLM_SUMMARY_LIMIT]
        return rating, summary

    first_line = content.strip().splitlines()[0] if content.strip() else ""
    match = re.search(r"\b([1-9]|10)\b", first_line)
    if match:
        rating = parse_int(match.group(1))
        rating = max(0, min(rating, 10))
        summary = content[len(first_line):].strip() or content.strip()
        return rating, summary[:LLM_SUMMARY_LIMIT]

    log.warning("LLM-ответ не распарсен: %r", content[:200])
    return 0, ""


@dataclass
class CollectedItem:

    source_id: int | None
    source_url: str
    raw_text: str
    media_urls: list[str] = field(default_factory=list)
    media_paths: list[Path] = field(default_factory=list)
    media_type_hint: str = MEDIA_TYPE_TEXT


MIN_TEXT_LENGTH = 30
MAX_FEED_ITEMS = 15


def collect_rss(source: dict, owner_id: int) -> list[CollectedItem]:
    feed_url = source["identifier"].strip()
    parsed = feedparser.parse(feed_url)
    if parsed.bozo and not parsed.entries:
        log.warning("RSS %s: фид не распарсен", feed_url)
        return []

    entries: list[CollectedItem] = []
    for entry in parsed.entries[:MAX_FEED_ITEMS]:
        title = (entry.get("title") or "").strip()
        summary = (entry.get("summary") or entry.get("description") or "").strip()
        link = (entry.get("link") or feed_url).strip()

        raw_text = (title + "\n\n" + summary).strip() if title and summary else (title or summary)
        if len(raw_text) < MIN_TEXT_LENGTH:
            continue

        img_urls = _extract_image_urls(entry)
        media_url = img_urls[0] if img_urls else None
        entries.append(CollectedItem(
            source_id=source["id"], source_url=link, raw_text=raw_text,
            media_urls=[media_url] if media_url else [],
            media_type_hint=MEDIA_TYPE_PHOTO if media_url else MEDIA_TYPE_TEXT,
        ))
    return entries


def _extract_image_urls(feed_entry: dict) -> list[str]:
    img_urls: list[str] = []

    # Обложка поста часто лежит во вложении (enclosure) с image-типом или картинкой-ссылкой.
    for enc in feed_entry.get("enclosures", []) or []:
        href = enc.get("href")
        is_image = (enc.get("type") or "").lower().startswith("image/")
        has_image_ext = str(href or "").lower().endswith(
            (".jpg", ".jpeg", ".png", ".webp", ".gif")
        )
        if href and (is_image or has_image_ext):
            img_urls.append(href)

    for media in feed_entry.get("media_content", []) or []:
        img_urls.append(media.get("url"))
    for media in feed_entry.get("media_thumbnail", []) or []:
        img_urls.append(media.get("url"))

    # Часть фидов держит картинку только в HTML-описании, а data-src появляется при ленивой загрузке.
    html_parts = [feed_entry.get("summary") or "", feed_entry.get("description") or ""]
    content = feed_entry.get("content") or []
    if content:
        html_parts.append(content[0].get("value") or "")
    img_urls += _IMG_RE.findall(" ".join(html_parts))

    unique_urls: list[str] = []
    for url in img_urls:
        if not isinstance(url, str):
            continue
        if not (url.startswith("http://") or url.startswith("https://")):
            continue
        if url in unique_urls:
            continue
        unique_urls.append(url)
    return unique_urls


COLLECTORS = {
    SOURCE_TYPE_RSS: collect_rss,
}


def process_collected(
    owner_id: int,
    collected: CollectedItem,
    moderation_kb_factory: Callable[[int], dict] | None,
    tg: MediaSender,
) -> int | None:
    dedup_hash = db.make_dedup_hash(collected.source_url, collected.raw_text)
    if db.exists_by_hash(owner_id, dedup_hash):
        log.info("Коллектор: дубликат пропущен (user=%s): %s", owner_id, collected.source_url)
        return None

    media_path: Path | None = None

    try:
        rating, summary = analyze(owner_id, collected.raw_text)

        threshold = db.get_effective_int(owner_id, SETTING_MIN_RATING, 6)
        if rating == 0 or rating < threshold:
            log.info("Коллектор: отсев по рейтингу %d < %d (user=%s) для %s",
                     rating, threshold, owner_id, collected.source_url)
            return None

        if collected.media_paths:
            media_path = collected.media_paths[0]
        elif collected.media_urls:
            user_agent = db.get_effective(owner_id, SETTING_DOWNLOAD_UA, DEFAULT_DOWNLOAD_UA)
            media_path = download(collected.media_urls[0], headers={"User-Agent": user_agent})
            if media_path:
                log.info("Коллектор: медиа скачано: %s", media_path)
            else:
                log.warning("Коллектор: медиа не скачано: %s", collected.media_urls[0])

        media_type = classify_media(media_path) if media_path else MEDIA_TYPE_TEXT
        post = db.create_post(
            owner_id=owner_id, source_id=collected.source_id, source_url=collected.source_url,
            raw_text=collected.raw_text, translated_text=summary, rating=rating,
            dedup_hash=dedup_hash, media_type=media_type, status=POST_STATUS_DRAFT,
        )
        log.info("Коллектор: создан черновик #%s (user=%s, rating=%d, text_len=%d)",
                 post["id"], owner_id, rating, len(summary))

        user = db.get_user(owner_id)
        if user is None:
            return None
        if moderation_kb_factory is None:
            moderation_kb_factory = lambda pid: keyboards.post_card_kb(
                pid, status=POST_STATUS_DRAFT, has_prev=False, has_next=False, offset=0,
            )

        caption_limit = (
            texts.MAX_CAPTION_LEN if media_path is not None else texts.MAX_TEXT_LEN
        ) - CAPTION_OVERHEAD
        caption_body = texts.truncate(summary or collected.raw_text, caption_limit)
        caption = (
            f"<b>Новый черновик</b>  ·  {rating}/10\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{html.escape(caption_body)}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"ID #{post['id']}"
        )
        file_id = tg.send_new_post(
            user["telegram_id"], caption, media_path, moderation_kb_factory(post["id"])
        )
        if file_id:
            db.set_media_file_id(owner_id, post["id"], file_id)
            log.info("Коллектор: сохранён file_id для поста #%s", post["id"])
        else:
            log.info("Коллектор: file_id не получен для поста #%s", post["id"])
        return post["id"]
    finally:
        cleanup(media_path)


def run_collection(tg: MediaSender) -> int:
    created_total = 0
    now = datetime.now(timezone.utc)
    users = db.list_active_users()
    log.info("Коллектор: активных пользователей: %d", len(users))

    for user in users:
        interval = db.get_effective_int(user["id"], SETTING_INTERVAL_MINUTES, 60)
        # В SQLite даты хранятся как наивные строки UTC без tzinfo, поэтому tz отрезается.
        cutoff = now.replace(tzinfo=None) - timedelta(minutes=interval)

        sources = db.list_active_sources(user["id"])
        if not sources:
            log.info("Коллектор: у пользователя %s нет активных источников", user["id"])

        for source in sources:
            last = source["last_fetched_at"]
            if last is not None:
                last_fetched = _parse_db_datetime(last)
                if last_fetched is not None and last_fetched >= cutoff:
                    log.info("Коллектор: источник %s не созрел (последний сбор %s)",
                             source["id"], last)
                    continue

            collector_fn = COLLECTORS.get(source["type"])
            if collector_fn is None:
                log.info("Коллектор: нет коллектора для типа %s", source["type"])
                db.mark_fetched(user["id"], source["id"])
                continue

            try:
                entries = collector_fn(source, user["id"])
            except Exception:
                log.exception("Коллектор %s упал (user=%s)", source["type"], user["id"])
                continue
            log.info("Коллектор: источник %s (%s) вернул элементов: %d",
                     source["id"], source["type"], len(entries))

            for collected in entries:
                try:
                    post_id = process_collected(user["id"], collected, None, tg)
                    if post_id is not None:
                        created_total += 1
                except Exception:
                    log.exception("Пайплайн упал на элементе (user=%s)", user["id"])

            db.mark_fetched(user["id"], source["id"])

    log.info("Коллектор: итого создано черновиков: %d", created_total)
    return created_total
