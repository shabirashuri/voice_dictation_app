from __future__ import annotations

import re


async def clean_text(text: str) -> str:
    """Simple cleaning for transcript chunks: normalize whitespace and punctuation."""
    if not text:
        return ""
    # normalize whitespace
    s = re.sub(r"\s+", " ", text).strip()
    # replace repeated punctuation
    s = re.sub(r"([\.\?\!]){2,}", r"\1", s)
    return s


async def clean_chunk_node(state) -> dict:
    """Node: read `state.current_chunk`, write `state.cleaned_chunk`.

    Returns a dict describing the cleaned_chunk written.
    Does not modify report fields.
    """
    chunk = getattr(state, "current_chunk", None)
    cleaned = await clean_text(chunk or "")
    state.cleaned_chunk = cleaned
    return {"cleaned_chunk": cleaned}
