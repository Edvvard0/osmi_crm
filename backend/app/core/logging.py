import logging

import structlog


def setup_logging(prod: bool, level: str = "INFO") -> None:
    num = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    logging.basicConfig(level=num, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer() if prod else structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(num),
    )
