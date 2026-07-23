"""
Nexus - Gemma 4 via Ollama (Local, RTX 4050)
Primary model: gemma4:e4b at http://localhost:11434
All inference runs locally. Zero cloud cost.

Adds a graceful-degradation chain: if the primary model 500s (typically OOM),
we try progressively smaller locally-pulled fallback models before giving up.
Errors are surfaced as structured dicts rather than swallowed as prose.
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple

import httpx

from backend.config import OLLAMA_CONFIG

logger = logging.getLogger("nexus.gemma4")


class Gemma4:
    """Interface to Ollama's local model server with fallback + retry."""

    def __init__(self):
        self.model = OLLAMA_CONFIG["model"]
        self.endpoint = OLLAMA_CONFIG["endpoint"]
        self.tags_endpoint = OLLAMA_CONFIG.get(
            "tags_endpoint", "http://localhost:11434/api/tags"
        )
        self.fallback_models: List[str] = list(
            OLLAMA_CONFIG.get("fallback_models", [])
        )
        self.max_tokens = OLLAMA_CONFIG["max_tokens"]
        self.max_tokens_fallback = OLLAMA_CONFIG.get("max_tokens_fallback", 400)
        self.temperature = OLLAMA_CONFIG["temperature"]
        self.timeout = OLLAMA_CONFIG.get("timeout_seconds", 120)
        self._available: Optional[bool] = None
        self._installed_models: List[str] = []
        self.last_error: Optional[str] = None
        self.last_model_used: Optional[str] = None

    # ------------------------------------------------------------------
    async def _fetch_installed(self) -> List[str]:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(self.tags_endpoint)
                data = resp.json()
                self._installed_models = [m.get("name", "") for m in data.get("models", [])]
        except Exception as e:
            logger.warning(f"Ollama /api/tags unreachable: {e}")
            self._installed_models = []
        return self._installed_models

    async def check_health(self) -> bool:
        await self._fetch_installed()
        primary_base = self.model.split(":")[0]
        self._available = any(primary_base in m for m in self._installed_models)
        return bool(self._available)

    def _fallback_chain(self) -> List[str]:
        """Return the fallback model list filtered to ones actually installed.

        If /api/tags hasn't been called yet we return the full configured list
        and let Ollama tell us what's missing (the model_not_found error path
        still works - it's just one extra round trip)."""
        if not self._installed_models:
            return list(self.fallback_models)
        installed_bases = {m.split(":")[0] for m in self._installed_models}
        return [fm for fm in self.fallback_models if fm.split(":")[0] in installed_bases]

    # ------------------------------------------------------------------
    async def _call_once(
        self,
        model: str,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Single Ollama call. Returns (response, error_reason). On success
        error_reason is None; on failure response is None."""
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if system:
            payload["system"] = system

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                start = time.time()
                resp = await client.post(self.endpoint, json=payload)
                elapsed = time.time() - start
                if resp.status_code == 200:
                    data = resp.json()
                    text = (data.get("response") or "").strip()
                    tokens = data.get("eval_count", 0)
                    logger.info(
                        f"Gemma4 ok model={model} tokens={tokens} elapsed={elapsed:.1f}s"
                    )
                    return text, None
                body = resp.text[:300]
                if "more system memory" in body or "out of memory" in body.lower():
                    reason = "oom"
                elif "model" in body and "not found" in body:
                    reason = "model_missing"
                else:
                    reason = f"http_{resp.status_code}"
                logger.error(
                    f"Gemma4 fail model={model} status={resp.status_code} reason={reason} body={body}"
                )
                return None, reason
        except httpx.TimeoutException:
            logger.error(f"Gemma4 timeout model={model}")
            return None, "timeout"
        except Exception as e:
            logger.error(f"Gemma4 exception model={model}: {e}")
            return None, f"exception:{e}"

    async def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: Optional[float] = None,
    ) -> str:
        """Generate text with automatic fallback to smaller installed models
        if the primary OOMs or 500s. Returns an empty string on total failure
        and records the reason in ``self.last_error`` for the caller."""
        temp = temperature if temperature is not None else self.temperature

        # Lazy-load installed model list so fallback filtering works.
        if not self._installed_models:
            await self._fetch_installed()

        attempts: List[Tuple[str, int]] = [(self.model, self.max_tokens)]
        for fb in self._fallback_chain():
            attempts.append((fb, self.max_tokens_fallback))

        seen: set = set()
        for model, tokens in attempts:
            if model in seen:
                continue
            seen.add(model)
            text, err = await self._call_once(model, prompt, system, temp, tokens)
            if text:
                self.last_error = None
                self.last_model_used = model
                return text
            # Don't waste time retrying non-recoverable errors on the same model
            if err in ("model_missing",):
                continue
            if err in ("oom", "timeout"):
                # Try next smaller model in chain
                await asyncio.sleep(0.2)
                continue
            # For generic http errors, give the next model one shot too
            continue

        self.last_error = "all_models_failed"
        self.last_model_used = None
        return ""

    # ------------------------------------------------------------------
    async def synthesize_brief(self, signals: Dict) -> str:
        system_prompt = (
            "You are Nexus, an institutional crypto derivatives trading assistant. "
            "Produce tight, data-dense briefs for a leverage-focused trader. "
            "Plain prose only. Do not use markdown syntax - no #, ##, **, backticks, "
            "or bullet characters. Use short section labels followed by a colon, "
            "then the data. Be direct. No filler, no preamble, no closing remarks."
        )
        prompt = f"""Write a morning trading brief from this signal data.

SIGNAL DATA:
{_format_signals(signals)}

Structure as six short labeled sections (one paragraph each, 1-2 sentences):
Zones: top 3 golden zones (tier, exchanges, type).
Derivatives: funding, OI trend, L/S ratio, squeeze risk.
Macro: upcoming events and gate status.
Leverage: current effective leverage and margin health.
Watchlist: top 3 zones to watch today with entry context.
Outlook: 2 sentence market view.

Rules: Under 220 words total. Specific numbers. No markdown characters. No lists - use flowing sentences. Start directly with "Zones:"."""
        return await self.generate(prompt, system=system_prompt)

    async def synthesize_news(
        self, headlines: list, sentiment: Optional[Dict] = None
    ) -> str:
        """Distill recent headlines into a 2-4 sentence narrative paragraph."""
        if not headlines:
            return ""

        # Keep the payload small - smaller models choke on long prompts and we
        # want the fallback chain to stay viable under memory pressure.
        trimmed = [str(h).strip() for h in headlines if str(h).strip()][:12]
        numbered = "\n".join(f"- {h}" for h in trimmed)

        sent_line = ""
        if sentiment:
            label = sentiment.get("sentiment", "neutral")
            score = sentiment.get("score", 0)
            sent_line = f"\nAggregate sentiment: {label} (score {score:+.2f})"

        system_prompt = (
            "You are Nexus's news desk. Given recent crypto market headlines, "
            "write one tight narrative paragraph (2-3 sentences) identifying "
            "the dominant storyline, any contradictions, and what a derivatives "
            "trader should care about. Plain prose only. No markdown, no bullets, "
            "no headings, no preamble - just the paragraph."
        )
        prompt = (
            f"Recent headlines:\n{numbered}{sent_line}\n\n"
            "Write the synthesis paragraph now."
        )
        return await self.generate(prompt, system=system_prompt, temperature=0.4)

    async def analyze_zone(self, zone_data: Dict, market_context: Dict) -> str:
        system_prompt = (
            "You are a crypto derivatives analyst. Analyze this liquidity zone "
            "and explain what it means for a leveraged trader. Be specific about "
            "risk at different leverage levels."
        )
        prompt = f"""Analyze this Golden Zone:
{_format_signals(zone_data)}

Market context:
{_format_signals(market_context)}

Explain: What is this zone? Why does it matter? What leverage is safe here? What's the liquidation risk?"""
        return await self.generate(prompt, system=system_prompt, temperature=0.3)


def _format_signals(data: Dict, indent: int = 0) -> str:
    lines = []
    prefix = "  " * indent
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{prefix}{key}:")
            lines.append(_format_signals(value, indent + 1))
        elif isinstance(value, list):
            lines.append(f"{prefix}{key}: [{len(value)} items]")
            for i, item in enumerate(value[:5]):
                if isinstance(item, dict):
                    lines.append(f"{prefix}  [{i}]:")
                    lines.append(_format_signals(item, indent + 2))
                else:
                    lines.append(f"{prefix}  - {item}")
        else:
            lines.append(f"{prefix}{key}: {value}")
    return "\n".join(lines)
