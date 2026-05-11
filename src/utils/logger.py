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

    log_dir = "logs"
    try:
        os.makedirs(log_dir, exist_ok=True)
        os.chmod(log_dir, 0o700)
        today = datetime.now().strftime("%Y%m%d")
        log_path = os.path.join(log_dir, f"trader_{today}.log")
        file_h = logging.FileHandler(log_path, encoding="utf-8")
        file_h.setFormatter(fmt)
        logger.addHandler(file_h)
        # New log files are owner-readable only.
        try:
            os.chmod(log_path, 0o600)
        except OSError:
            pass
    except OSError as e:
        console.handleError = lambda r: None
        logger.warning(f"File logging disabled: {e}")

    return logger
