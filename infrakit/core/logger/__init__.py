"""
infrakit.core.logger
~~~~~~~~~~~~~~~~~~~~~
Public surface — import only from here.

    from infrakit.core.logger import setup, get_logger

    setup(
        level    = "INFO",
        strategy = "date_level",
        stream   = "stdout",
        session  = True,
        retention = 30,
    )
    log = get_logger(__name__)
    log.info("Ready")
"""

from infrakit.core.logger.setup import get_logger, reset, setup

__all__ = ["setup", "get_logger", "reset"]