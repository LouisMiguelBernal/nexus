"""
Nexus - Alert Scheduler
Runs 60-second zone check loop + morning brief at 08:00.
"""

import asyncio
import logging
import time
from typing import Optional

from backend.alerts.telegram import TelegramBot
from backend.storage.alerts import save_alert

logger = logging.getLogger("nexus.scheduler")


class AlertScheduler:
    """APScheduler-based alert loop."""

    def __init__(self, telegram: TelegramBot):
        self.telegram = telegram
        self._running = False
        self._zone_check_interval = 60  # seconds
        self._check_callback = None

    def set_zone_check_callback(self, callback):
        """Set the async callback that runs every 60s to check zones."""
        self._check_callback = callback

    async def start(self):
        """Start the alert check loop."""
        self._running = True
        logger.info("Alert scheduler started (60s interval)")
        while self._running:
            try:
                if self._check_callback:
                    alerts = await self._check_callback()
                    if alerts:
                        for alert in alerts:
                            await self._process_alert(alert)
            except Exception as e:
                logger.error(f"Alert check error: {e}")
            await asyncio.sleep(self._zone_check_interval)

    async def stop(self):
        self._running = False
        logger.info("Alert scheduler stopped")

    async def _process_alert(self, alert: dict):
        """Process and send a single alert."""
        alert_type = alert.get("type", "unknown")
        symbol = alert.get("symbol", "")
        message = alert.get("message", str(alert))

        # Save to DB
        save_alert(
            alert_type=alert_type,
            message=message,
            symbol=symbol,
            data=alert,
            sent_telegram=self.telegram.configured,
        )

        # Send via Telegram
        if self.telegram.configured:
            await self.telegram.send_alert(alert_type, alert)
