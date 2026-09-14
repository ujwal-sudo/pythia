import logging
from logging import Logger

from config import LOG_FILE


_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def get_logger(name: str) -> Logger:
    """Return a configured logger for pipeline modules."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

        formatter = logging.Formatter(_LOG_FORMAT)
        file_handler = logging.FileHandler(LOG_FILE)
        console_handler = logging.StreamHandler()
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger
