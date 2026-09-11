"""
Nexus - Telegram Bot API Wrapper
Sends alerts to configured chat. Free, no limit.
"""

import logging
from typing import Optional

import httpx

from backend.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger("nexus.telegram")


class TelegramBot:
    """Send messages via Telegram Bot API."""

    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}" if self.token else ""

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message to the configured chat."""
        if not self.configured:
            logger.warning("Telegram not configured (missing token or chat_id)")
            return False

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.base_url}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": text,
                        "parse_mode": parse_mode,
                        "disable_web_page_preview": True,
                    },
                )
                if resp.status_code == 200:
                    logger.info(f"Telegram sent: {text[:80]}...")
                    return True
                else:
                    logger.error(f"Telegram error {resp.status_code}: {resp.text[:200]}")
                    return False
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    async def send_alert(self, alert_type: str, data: dict) -> bool:
        """Send a formatted alert based on type."""
        formatters = {
            "zone_approach": self._format_zone_approach,
            "zone_hit": self._format_zone_hit,
            "macro_danger": self._format_macro_danger,
            "squeeze_alert": self._format_squeeze,
            "leverage_warning": self._format_leverage_warning,
            "circuit_breaker": self._format_circuit_breaker,
            "morning_brief": self._format_morning_brief,
        }
        formatter = formatters.get(alert_type)
        if not formatter:
            return await self.send_message(f"[{alert_type}] {str(data)[:500]}")
        return await self.send_message(formatter(data))

    def _format_zone_approach(self, d: dict) -> str:
        return (
            f"⚠️ <b>{d.get('symbol', '?')} approaching {d.get('tier', '?')} zone</b>\n"
            f"Price: ${d.get('price', 0):,.2f}\n"
            f"Zone type: {d.get('zone_type', '?')} | Exchanges: {d.get('exchange_count', 0)}\n"
            f"Funding: {d.get('funding', 0):.4f}% | OI trend: {d.get('oi_trend', '?')}\n"
            f"Squeeze: Long {d.get('long_squeeze', 0):.0f}% / Short {d.get('short_squeeze', 0):.0f}%\n"
            f"Macro: {d.get('macro_status', 'open')}"
        )

    def _format_zone_hit(self, d: dict) -> str:
        return (
            f"🎯 <b>{d.get('symbol', '?')} HIT {d.get('tier', '?')} zone</b>\n"
            f"Price: ${d.get('price', 0):,.2f}\n"
            f"{d.get('context', '')}"
        )

    def _format_macro_danger(self, d: dict) -> str:
        return (
            f"🔴 <b>MACRO GATE ACTIVE</b>\n"
            f"{d.get('event_name', '?')} in {d.get('minutes_until', 0):.0f}min\n"
            f"Threshold raised to {d.get('confidence_threshold', 0.85)}\n"
            f"Position size capped at {d.get('max_position_pct', 0.5):.1f}%"
        )

    def _format_squeeze(self, d: dict) -> str:
        return (
            f"💥 <b>SQUEEZE RISK: {d.get('direction', '?')} squeeze {d.get('risk_pct', 0):.0f}%</b>\n"
            f"Symbol: {d.get('symbol', '?')}\n"
            f"Nearest liq cluster: ${d.get('cluster_price', 0):,.2f} ({d.get('distance_pct', 0):.1f}% away)\n"
            f"Est. cascade: ${d.get('cascade_usd', 0):,.0f}"
        )

    def _format_leverage_warning(self, d: dict) -> str:
        return (
            f"⚡ <b>LEVERAGE WARNING</b>\n"
            f"{d.get('symbol', '?')} at {d.get('leverage', 0)}x effective\n"
            f"Margin ratio: {d.get('margin_ratio', 0):.1f}%\n"
            f"Liquidation at: ${d.get('liq_price', 0):,.2f} ({d.get('distance_pct', 0):.1f}% away)"
        )

    def _format_circuit_breaker(self, d: dict) -> str:
        return (
            f"🛑 <b>CIRCUIT BREAKER TRIGGERED</b>\n"
            f"Daily loss: {d.get('daily_loss_pct', 0):.2f}% | Peak drawdown: {d.get('drawdown_pct', 0):.2f}%\n"
            f"All signals suppressed until: {d.get('reset_time', '00:00 UTC')}\n"
            f"Reduce leverage and review positions."
        )

    def _format_morning_brief(self, d: dict) -> str:
        return f"📊 <b>NEXUS Morning Brief</b>\n\n{d.get('brief', 'No brief generated')}"
