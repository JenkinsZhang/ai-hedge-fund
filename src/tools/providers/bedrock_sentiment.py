"""Batch sentiment annotation via Bedrock Haiku 4.5.

Reuses the existing ChatBedrockConverse path from src.llm.models.
"""

from __future__ import annotations

import json
import logging
import os

from src.data.models import CompanyNews

logger = logging.getLogger(__name__)

# Pick the cross-region inference profile that matches AWS_REGION.
# Default jp.* for ap-northeast-1 (matches the Bedrock provider's default).
_HAIKU_MODEL_BY_REGION = {
    "ap-northeast-1": "jp.anthropic.claude-haiku-4-5",
    "us-east-1":      "us.anthropic.claude-haiku-4-5",
    "us-east-2":      "us.anthropic.claude-haiku-4-5",
    "us-west-2":      "us.anthropic.claude-haiku-4-5",
    "eu-west-1":      "eu.anthropic.claude-haiku-4-5",
    "eu-central-1":   "eu.anthropic.claude-haiku-4-5",
}


def _haiku_model() -> str:
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "ap-northeast-1"
    return _HAIKU_MODEL_BY_REGION.get(region, "jp.anthropic.claude-haiku-4-5")

_PROMPT = (
    "Classify each news title's sentiment toward the listed ticker. "
    "Return ONLY a JSON object with this exact shape: "
    '{"items":[{"i":<int>,"s":"bullish|bearish|neutral"}]}. '
    "No prose. No code fences."
)


def _invoke_haiku(prompt: str) -> str:
    """Call Haiku via the existing get_model path; return raw content."""
    from src.llm.models import ModelProvider, get_model
    llm = get_model(_haiku_model(), ModelProvider.BEDROCK)
    msg = llm.invoke(prompt)
    return msg.content if hasattr(msg, "content") else str(msg)


def annotate(news: list[CompanyNews]) -> list[CompanyNews]:
    """Set news[i].sentiment in-place. On any error, default to 'neutral'."""
    if not news:
        return news

    items_block = "\n".join(
        f"{i}. ticker={n.ticker} title={json.dumps(n.title)}"
        for i, n in enumerate(news)
    )
    full_prompt = f"{_PROMPT}\n\nItems:\n{items_block}"

    try:
        raw = _invoke_haiku(full_prompt)
        # Strip code fences if model added them
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.lstrip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:]
            raw = raw.strip().rstrip("`").strip()
        parsed = json.loads(raw)
        labels = {item["i"]: item["s"] for item in parsed.get("items", [])}
    except Exception as exc:
        logger.warning("Bedrock sentiment annotation failed: %s", exc)
        for n in news:
            if n.sentiment is None:
                n.sentiment = "neutral"
        return news

    for i, n in enumerate(news):
        n.sentiment = labels.get(i, "neutral")
    return news
