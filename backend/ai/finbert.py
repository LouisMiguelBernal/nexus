"""
Nexus - FinBERT Local Sentiment Scorer
Model: ProsusAI/finbert via HuggingFace transformers
Runs on RTX 4050 (~400MB VRAM). Target: <50ms per headline.
"""

import logging
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nexus.finbert")

# Lazy-loaded to avoid import cost at startup
_pipeline = None
_device = None


def _load_model():
    """Lazy load FinBERT model on first use."""
    global _pipeline, _device
    if _pipeline is not None:
        return

    from backend.config import FINBERT_CONFIG

    try:
        import torch
        from transformers import pipeline

        device_str = FINBERT_CONFIG["device"]
        if device_str == "cuda" and not torch.cuda.is_available():
            logger.warning("CUDA not available, falling back to CPU")
            device_str = "cpu"

        _device = device_str
        _pipeline = pipeline(
            "sentiment-analysis",
            model=FINBERT_CONFIG["model"],
            device=0 if device_str == "cuda" else -1,
            batch_size=FINBERT_CONFIG["batch_size"],
        )
        logger.info(f"FinBERT loaded on {device_str}")
    except Exception as e:
        logger.error(f"FinBERT load failed: {e}")
        _pipeline = None


class FinBERTScorer:
    """Score news headlines for financial sentiment."""

    def __init__(self):
        self.threshold = 0.75  # Only use if confidence > 75%

    def score_headline(self, text: str) -> Dict:
        """
        Score a single headline.
        Returns label (positive/negative/neutral) and confidence.
        """
        _load_model()
        if _pipeline is None:
            return {"label": "neutral", "score": 0.0, "usable": False, "error": "model_not_loaded"}

        try:
            start = time.time()
            result = _pipeline(text[:512])[0]  # Truncate to model max
            elapsed_ms = (time.time() - start) * 1000

            label = result["label"]
            score = result["score"]

            return {
                "label": label,
                "score": round(score, 4),
                "usable": score >= self.threshold,
                "inference_ms": round(elapsed_ms, 1),
                "text": text[:100],
            }
        except Exception as e:
            logger.error(f"FinBERT inference error: {e}")
            return {"label": "neutral", "score": 0.0, "usable": False, "error": str(e)}

    def score_batch(self, headlines: List[str]) -> List[Dict]:
        """Score a batch of headlines efficiently."""
        _load_model()
        if _pipeline is None:
            return [{"label": "neutral", "score": 0.0, "usable": False} for _ in headlines]

        try:
            start = time.time()
            truncated = [h[:512] for h in headlines]
            results = _pipeline(truncated)
            elapsed_ms = (time.time() - start) * 1000

            scored = []
            for i, result in enumerate(results):
                scored.append({
                    "label": result["label"],
                    "score": round(result["score"], 4),
                    "usable": result["score"] >= self.threshold,
                    "text": headlines[i][:100],
                })

            logger.info(f"FinBERT batch: {len(headlines)} headlines in {elapsed_ms:.0f}ms")
            return scored
        except Exception as e:
            logger.error(f"FinBERT batch error: {e}")
            return [{"label": "neutral", "score": 0.0, "usable": False} for _ in headlines]

    def aggregate_sentiment(self, scored: List[Dict]) -> Dict:
        """Aggregate scored headlines into a market sentiment summary."""
        usable = [s for s in scored if s.get("usable")]
        if not usable:
            return {"sentiment": "neutral", "confidence": 0, "sample_size": 0}

        positive = sum(1 for s in usable if s["label"] == "positive")
        negative = sum(1 for s in usable if s["label"] == "negative")
        neutral = sum(1 for s in usable if s["label"] == "neutral")
        total = len(usable)

        avg_score = sum(s["score"] for s in usable) / total

        if positive > negative and positive > neutral:
            sentiment = "positive"
        elif negative > positive and negative > neutral:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        return {
            "sentiment": sentiment,
            "confidence": round(avg_score, 4),
            "positive_count": positive,
            "negative_count": negative,
            "neutral_count": neutral,
            "sample_size": total,
            "total_headlines": len(scored),
        }
