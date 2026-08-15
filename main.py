import logging
import sys

import bot
import db
from config import BOT_TOKEN, DB_PATH, LOG_LEVEL, ensure_runtime_dirs

COLLECTOR_EVERY_SECONDS = 60


def configure_logging() -> None:
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logging.getLogger("requests").setLevel(logging.WARNING)


def main() -> None:
    configure_logging()
    log = logging.getLogger(__name__)
    log.info("=== ContentCurator (easy) startup ===")

    ensure_runtime_dirs()
    db.init_db()
    log.info("БД готова: %s", DB_PATH)

    tg = bot.Telegram(BOT_TOKEN)
    try:
        bot.run(tg, collector_every=COLLECTOR_EVERY_SECONDS)
    except KeyboardInterrupt:
        log.info("Получен сигнал остановки. Bye.")


if __name__ == "__main__":
    main()