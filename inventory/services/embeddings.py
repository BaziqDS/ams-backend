"""
Embedding client for the agent's hybrid item search.

OpenAI-compatible HTTP API only — the BASE_URL is configurable so this works
against OpenRouter (default, for testing) or OpenAI directly (production).

Public surface:
    embed_text(text) -> list[float] | None
    embed_item(item) -> tuple[hash, vector | None]
    build_item_embedding_text(item) -> str

We never raise on transient API failures — embedding is best-effort. The
caller (post_save signal, backfill command) records the failure and the
nightly backfill retries.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)


# ---- Client cache --------------------------------------------------------

_client = None


def _get_client():
    """Lazy-instantiate the OpenAI SDK client pointed at EMBEDDING_BASE_URL."""
    global _client
    if _client is not None:
        return _client
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        logger.warning("openai package not installed: %s", exc)
        return None

    api_key = (settings.EMBEDDING_API_KEY or '').strip()
    if not api_key:
        logger.warning(
            "EMBEDDING_API_KEY is not set — embeddings disabled. "
            "Set EMBEDDING_API_KEY to your OpenRouter or OpenAI key."
        )
        return None

    _client = OpenAI(
        api_key=api_key,
        base_url=settings.EMBEDDING_BASE_URL,
        timeout=settings.EMBEDDING_TIMEOUT_SECONDS,
    )
    return _client


# ---- Text construction ---------------------------------------------------

def build_item_embedding_text(item) -> str:
    """
    Build the symmetric text representation used both for indexing an Item and
    for encoding a query at search time. Labeled, structured form helps the
    embedding model anchor each field's role.
    """
    parts = []
    if getattr(item, 'name', None):
        parts.append(f"NAME: {item.name}")
    if getattr(item, 'code', None):
        parts.append(f"CODE: {item.code}")

    # Category path (parent → leaf) is the most useful classification signal.
    category = getattr(item, 'category', None)
    if category is not None:
        chain = []
        cursor = category
        # Walk up at most a few levels to avoid runaway loops on bad data.
        for _ in range(6):
            if cursor is None:
                break
            name = getattr(cursor, 'name', None)
            if name:
                chain.append(name)
            cursor = getattr(cursor, 'parent_category', None)
        if chain:
            parts.append(f"CATEGORY: {' / '.join(reversed(chain))}")

    if getattr(item, 'description', None):
        parts.append(f"DESCRIPTION: {item.description}")
    if getattr(item, 'specifications', None):
        parts.append(f"SPECIFICATIONS: {item.specifications}")
    if getattr(item, 'acct_unit', None):
        parts.append(f"UNIT: {item.acct_unit}")

    return "\n".join(parts)


def build_query_text(*, name='', code='', category='', description='',
                     specifications='', unit='') -> str:
    """
    Build a query string with the SAME shape used for indexed items, so
    cosine similarity is meaningful. Pass the inspection-row fields here.
    """
    parts = []
    if name:
        parts.append(f"NAME: {name}")
    if code:
        parts.append(f"CODE: {code}")
    if category:
        parts.append(f"CATEGORY: {category}")
    if description:
        parts.append(f"DESCRIPTION: {description}")
    if specifications:
        parts.append(f"SPECIFICATIONS: {specifications}")
    if unit:
        parts.append(f"UNIT: {unit}")
    return "\n".join(parts)


def hash_text(text: str) -> str:
    """Deterministic short hash used to skip redundant re-embeds."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


# ---- Embedding calls -----------------------------------------------------

@dataclass
class EmbedResult:
    text: str
    text_hash: str
    vector: Optional[list]
    error: Optional[str] = None


def embed_text(text: str) -> Optional[list]:
    """
    Synchronously embed a single string. Returns None on any failure
    (missing API key, network error, dimension mismatch).
    """
    if not text or not text.strip():
        return None

    client = _get_client()
    if client is None:
        return None

    try:
        response = client.embeddings.create(
            model=settings.EMBEDDING_MODEL,
            input=text,
        )
    except Exception as exc:
        logger.warning("Embedding call failed: %s", exc)
        return None

    try:
        vector = response.data[0].embedding
    except (AttributeError, IndexError, TypeError) as exc:
        logger.warning("Unexpected embedding response shape: %s", exc)
        return None

    expected_dim = getattr(settings, 'EMBEDDING_DIM', None)
    if expected_dim and len(vector) != expected_dim:
        logger.warning(
            "Embedding dimension %d does not match EMBEDDING_DIM=%d "
            "(model=%s). Update settings or pick a matching model.",
            len(vector), expected_dim, settings.EMBEDDING_MODEL,
        )
        return None

    return list(vector)


def embed_item(item) -> EmbedResult:
    """
    Build the canonical text for an Item and embed it. Always returns an
    EmbedResult so callers can persist the hash even when the vector failed.
    """
    text = build_item_embedding_text(item)
    text_hash = hash_text(text)
    if not text:
        return EmbedResult(text='', text_hash=text_hash, vector=None,
                           error='empty_text')
    vector = embed_text(text)
    if vector is None:
        return EmbedResult(text=text, text_hash=text_hash, vector=None,
                           error='embed_failed')
    return EmbedResult(text=text, text_hash=text_hash, vector=vector)
