import logging
import os
import sys
from datetime import datetime


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logger.addHandler(console)

    os.makedirs("logs", exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    file_h = logging.FileHandler(f"logs/trader_{today}.log", encoding="utf-8")
    file_h.setFormatter(fmt)
    logger.addHandler(file_h)

    return logger
