import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


BASE_DIR: Path = Path(__file__).resolve().parent

DATA_DIR: Path = BASE_DIR / "data"
DB_PATH: Path = Path(os.getenv("DB_PATH", str(DATA_DIR / "content.db")))

TMP_DIR: Path = Path(os.getenv("TMP_DIR", str(BASE_DIR / "tmp")))


BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

ADMIN_IDS: tuple[int, ...] = tuple(
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
)

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

POST_STATUS_DRAFT = "draft"
POST_STATUS_APPROVED = "approved"
POST_STATUS_ARCHIVED = "archived"
POST_STATUS_REJECTED = "rejected"

USER_STATUS_PENDING = "pending"
USER_STATUS_ACTIVE = "active"
USER_STATUS_BLOCKED = "blocked"

SOURCE_TYPE_RSS = "rss"

MEDIA_TYPE_PHOTO = "photo"
MEDIA_TYPE_VIDEO = "video"
MEDIA_TYPE_ANIMATION = "animation"
MEDIA_TYPE_DOCUMENT = "document"
MEDIA_TYPE_TEXT = "text"

SETTING_AI_API_KEY = "ai_api_key"
SETTING_AI_BASE_URL = "ai_base_url"
SETTING_AI_MODEL = "ai_model_collector"
SETTING_DOWNLOAD_UA = "download_user_agent"
SETTING_TARGET_CHANNEL = "target_channel_id"
SETTING_INTERVAL_MINUTES = "collector_interval_minutes"
SETTING_MIN_RATING = "min_rating_threshold"
SETTING_SYSTEM_PROMPT = "system_prompt_collector"


DEFAULT_DOWNLOAD_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


DEFAULT_SETTINGS: dict[str, str] = {
    SETTING_AI_API_KEY: "",
    SETTING_AI_BASE_URL: "https://open.bigmodel.cn/api/paas/v4/",
    SETTING_AI_MODEL: "glm-4-flash",

    SETTING_DOWNLOAD_UA: DEFAULT_DOWNLOAD_UA,

    SETTING_TARGET_CHANNEL: "",

    SETTING_INTERVAL_MINUTES: "60",

    SETTING_MIN_RATING: "6",

    SETTING_SYSTEM_PROMPT: (
        "Ты - аналитик контента технических каналов. Получив сырой пост, оцени его "
        "релевантность для технической аудитории (1-10) и сделай краткий перевод на "
        "русский язык. Ответ строго в формате JSON: "
        '{"rating": <int 1-10>, "summary": "<перевод/выжимка>"}'
    ),
}


def ensure_runtime_dirs() -> None:
    for directory in (DATA_DIR, TMP_DIR):
        directory.mkdir(parents=True, exist_ok=True)