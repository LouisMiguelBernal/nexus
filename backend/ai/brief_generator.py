"""
Nexus - Morning Brief Generator
Collects all L2 signals and feeds them to Gemma 4 for synthesis.
Delivered via Telegram at 08:00 daily.
"""

import logging
import time
from typing import Dict, Optional

from backend.ai.gemma4 import Gemma4
from backend.ai.finbert import FinBERTScorer

logger = logging.getLogger("nexus.brief_generator")


class BriefGenerator:
    """Generates daily morning briefs using Gemma 4."""

    def __init__(self):
        self.gemma = Gemma4()
        self.finbert = FinBERTScorer()
        self._last_brief: Optional[Dict] = None
        self._last_brief_time: float = 0

    async def generate_brief(
        self,
        golden_zones: list,
        funding_data: dict,
        oi_data: dict,
        squeeze_data: dict,
        macro_status: dict,
        margin_data: Optional[dict] = None,
        news_headlines: Optional[list] = None,
    ) -> Dict:
        """
        Generate a full morning brief.
        Collects all signal data, scores news, sends to Gemma 4.
        """
        # Score news if available
        sentiment = {}
        if news_headlines:
            scored = self.finbert.score_batch(news_headlines)
            sentiment = self.finbert.aggregate_sentiment(scored)

        # Build signal context for Gemma 4
        signals = {
            "golden_zones": [
                z.to_dict() if hasattr(z, "to_dict") else z
                for z in (golden_zones or [])[:10]
            ],
            "funding": funding_data or {},
            "open_interest": oi_data or {},
            "squeeze_risk": squeeze_data or {},
            "macro_gate": macro_status or {},
            "news_sentiment": sentiment,
            # Pass the raw top headlines so Gemma can synthesize an actual
            # news paragraph, not just consume an aggregate sentiment score.
            "top_headlines": (news_headlines or [])[:12],
        }

        if margin_data:
            signals["portfolio_margin"] = margin_data

        # Generate brief via Gemma 4 (structured signals + headlines)
        brief_text = await self.gemma.synthesize_brief(signals)
        brief_error = self.gemma.last_error
        brief_model = self.gemma.last_model_used

        # News synthesis paragraph: an explicit 2nd LLM call dedicated to
        # distilling the headlines into a narrative paragraph.
        news_synthesis = ""
        news_error: Optional[str] = None
        news_model: Optional[str] = None
        if news_headlines:
            news_synthesis = await self.gemma.synthesize_news(
                news_headlines[:15], sentiment=sentiment,
            )
            news_error = self.gemma.last_error
            news_model = self.gemma.last_model_used

        # Map opaque error keys to a user-facing message.
        def _explain(err: Optional[str]) -> Optional[str]:
            if not err:
                return None
            if err == "oom" or err == "all_models_failed":
                return (
                    "Local LLM out of memory. Close other apps or pull a "
                    "smaller Ollama model (gemma2:2b, llama3.2:1b)."
                )
            if err == "timeout":
                return "Local LLM timed out. Retry or try a smaller model."
            return f"LLM unavailable ({err})."

        result = {
            "brief": brief_text,
            "news_synthesis": news_synthesis,
            "generated_at": time.time(),
            "signals_used": list(signals.keys()),
            "zone_count": len(signals["golden_zones"]),
            "news_sentiment": sentiment.get("sentiment", "unknown"),
            "news_count": len(news_headlines or []),
            "macro_status": macro_status.get("status", "unknown") if macro_status else "unknown",
            "brief_error": _explain(brief_error) if not brief_text else None,
            "news_error": _explain(news_error) if not news_synthesis and news_headlines else None,
            "model_used": brief_model or news_model,
            "ok": bool(brief_text or news_synthesis),
        }

        self._last_brief = result
        self._last_brief_time = time.time()

        return result

    @property
    def last_brief(self) -> Optional[Dict]:
        return self._last_brief
