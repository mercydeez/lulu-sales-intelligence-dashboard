"""Unit tests for RAG cache key scoping (GR-5). Pure — no Redis.
The answer-cache key MUST include the ACL scope: a cache leak across roles is a
security bug, so these assertions are security assertions."""
from app.services.rag.cache import answer_key, embedding_key


def test_answer_key_differs_by_acl_scope():
    q = "which stores are low on dairy?"
    # same question, DIFFERENT authorization => DIFFERENT key (no cross-role leak)
    assert answer_key(q, "aclA", 1) != answer_key(q, "aclB", 1)


def test_answer_key_stable_for_same_scope():
    q = "revenue last week"
    assert answer_key(q, "aclA", 1) == answer_key(q, "aclA", 1)


def test_answer_key_differs_by_tenant():
    q = "revenue"
    assert answer_key(q, "aclA", 1) != answer_key(q, "aclA", 2)


def test_answer_key_normalizes_question():
    # case + punctuation + whitespace insensitive
    assert answer_key("Dubai Sales?", "h", 1) == answer_key("dubai   sales", "h", 1)


def test_embedding_key_scoped_by_model():
    # vectors from different embedders must never collide in cache
    assert embedding_key("abc", "m1") != embedding_key("abc", "m2")
    assert embedding_key("abc", "m1") == embedding_key("abc", "m1")
