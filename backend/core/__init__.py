"""Nexus core: event bus, task supervisor, clock, typed events, symbol registry, caches.

Everything in here is pure infrastructure with no knowledge of venues or
strategies. Strictly typed (mypy --strict) from day one.
"""
