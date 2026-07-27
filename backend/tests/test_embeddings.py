"""Unit tests for the hashed-fallback embedder (Sage Stage 1).
Exercises the zero-dependency path — no model server needed."""
import math

import pytest

from app.services.embeddings import (
    EMBED_DIM,
    HASHED_MODEL_TAG,
    embed_texts,
    to_pgvector_literal,
    _hashed_embed_one,
)


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b))


def test_dim_and_normalized():
    v = _hashed_embed_one("Dubai revenue dropped during Ramadan")
    assert len(v) == EMBED_DIM
    assert math.sqrt(sum(x * x for x in v)) == pytest.approx(1.0, abs=1e-6)


def test_deterministic_across_calls():
    assert _hashed_embed_one("same text here") == _hashed_embed_one("same text here")


def test_lexical_overlap_beats_unrelated():
    a = _hashed_embed_one("sales revenue dubai store")
    b = _hashed_embed_one("revenue sales dubai outlet")   # 3 shared tokens
    c = _hashed_embed_one("penguin antarctica iceberg")   # 0 shared tokens
    assert _cos(a, b) > _cos(a, c)


def test_empty_text_is_zero_vector():
    v = _hashed_embed_one("")
    assert len(v) == EMBED_DIM and all(x == 0.0 for x in v)


@pytest.mark.asyncio
async def test_embed_texts_batch_tagged_and_sized():
    res = await embed_texts(["one", "two", "three"])
    assert len(res.vectors) == 3
    assert res.dim == EMBED_DIM
    # No model server in the test env -> hashed fallback, flagged non-semantic.
    assert res.model == HASHED_MODEL_TAG
    assert res.semantic is False


@pytest.mark.asyncio
async def test_embed_empty_batch():
    res = await embed_texts([])
    assert res.vectors == []


def test_pgvector_literal_format():
    lit = to_pgvector_literal([0.5, -0.25, 1.0])
    assert lit.startswith("[") and lit.endswith("]")
    assert lit.count(",") == 2


def test_detect_lang_arabic_vs_english():
    from app.services.embeddings import detect_lang
    assert detect_lang("increase dairy stock before Ramadan") == "en"
    assert detect_lang("زيادة مخزون الألبان قبل رمضان") == "ar"
    assert detect_lang("") == "en"
