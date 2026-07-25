import logging
import sys

from app.core.config import get_settings


def configure_logging() -> None:
    """One place to configure logging so every module gets consistent output.

    This is a plain formatted stream handler for local development. Swapping
    in JSON structured logging later only means changing this function —
    call sites elsewhere in the app just use `logging.getLogger(__name__)`.
    """
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
