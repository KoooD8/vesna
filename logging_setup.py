import json
import logging
from pythonjsonlogger import jsonlogger


def setup_json_logger(level: int = logging.INFO) -> None:
    logger = logging.getLogger()
    logger.handlers = []
    logger.setLevel(level)
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

