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
        "Ты — редактор telegram канала."
        "На вход придёт «сырой» фрагмент из RSS (заголовок и описание, с HTML-мусором "
        "и служебной разметкой). Игнорируй разметку и оценивай только реальную суть "
        "материала.\n"
        "\n"
        "Верни ровно один JSON-объект без пояснений и markdown-блоков:\n"
        '{"rating": 7, "summary": "..."}\n'
        "\n"
        "1) rating (целое 1–10) - насколько материал ценен для канала:\n"
        "9–10 - редкий, глубокий, ключевой;\n"
        "7–8 - хороший профильный материал, зайдёт большинству;\n"
        "5–6 - близко к теме, но вторично или поверхностно;\n"
        "1–4 - оффтоп, кликбейт, реклама, спам. "
        "К таким ставь 1–2.\n"
        "Будь строгим: сомнительное занижай, не завышай.\n"
        "\n"
        "2) summary - готовый пост для публикации, на русском языке:\n"
        "цепляющий первый абзац → суть → пара деталей → короткий вывод;\n"
        "обычный текст без HTML и markdown (разметка не отобразится): эмодзи, длинные "
        "тире, короткие абзацы приветствуются;\n"
        "строго по фактам исходника: не выдумывай даты, характеристики, платформы и "
        "имена; при сомнении пиши обобщённо;\n"
        "не добавляй ссылки и URL — канал проставит их сам;\n"
        "длина 600–900 символов, не больше 950.\n"
        "\n"
        "Переносы строк внутри summary оформляй как \\n, двойные кавычки как \\\", "
        "чтобы JSON был валидным."
    ),
}


def ensure_runtime_dirs() -> None:
    for directory in (DATA_DIR, TMP_DIR):
        directory.mkdir(parents=True, exist_ok=True)