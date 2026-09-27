from __future__ import annotations

import json
import logging
import sys

from app.logs import JsonFormatter, configure_logging


def test_json_formatter_includes_extras_and_exceptions() -> None:
    record = logging.makeLogRecord(
        {"name": "x", "levelname": "INFO", "msg": "hello %s", "args": ("world",), "ip": "1.2.3.4"}
    )
    payload = json.loads(JsonFormatter().format(record))
    assert payload["msg"] == "hello world"
    assert payload["ip"] == "1.2.3.4"
    assert payload["level"] == "INFO"

    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.makeLogRecord({"msg": "failed", "exc_info": sys.exc_info()})
    assert "boom" in json.loads(JsonFormatter().format(record))["exc"]


def test_configure_logging_sets_level() -> None:
    configure_logging("WARNING")
    root = logging.getLogger()
    assert root.level == logging.WARNING
    assert isinstance(root.handlers[0].formatter, JsonFormatter)
    assert logging.getLogger("uvicorn.access").propagate
