"""Logging helpers for hot loops.

A failure inside a 2-second loop must be visible - but not 30 times a minute.
:func:`warn_throttled` emits at WARNING once per key per window and demotes
the repeats to DEBUG, so the log says "this is broken" without drowning
everything else.
"""

from __future__ import annotations

import logging
import threading
import time

_last_emit: dict[str, float] = {}
_lock = threading.Lock()


def warn_throttled(
    logger: logging.Logger,
    key: str,
    msg: str,
    *args: object,
    every_s: float = 600.0,
    exc_info: bool = False,
) -> bool:
    """Log ``msg`` at WARNING at most once per ``every_s`` seconds per ``key``.

    Suppressed repeats are logged at DEBUG. Returns True when the WARNING was
    emitted.
    """
    now = time.monotonic()
    with _lock:
        last = _last_emit.get(key)
        emit = last is None or (now - last) >= every_s
        if emit:
            _last_emit[key] = now
    if emit:
        logger.warning(msg + " (repeats suppressed for %ds)", *args, int(every_s), exc_info=exc_info)
    else:
        logger.debug(msg, *args)
    return emit


def reset_throttle() -> None:
    """Test hook."""
    with _lock:
        _last_emit.clear()
