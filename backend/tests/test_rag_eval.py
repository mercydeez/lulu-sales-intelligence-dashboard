"""EVAL-1: RAG evaluation harness + CI gate (retrieval metrics). Pure."""
from app.services.rag.evaluation import (
    recall_at_k, mrr, evaluate_retrieval, RetrievalReport,
)


def test_recall_at_k_math():
    assert recall_at_k([1, 2, 3], [2], 3) == 1.0
    assert recall_at_k([1, 2, 3], [9], 3) == 0.0
    assert recall_at_k([1, 2, 3, 4], [2, 4], 2) == 0.5   # only 2 in top-2
    assert recall_at_k([1], [], 1) == 1.0                # no relevant => trivially 1


def test_mrr_math():
    assert mrr([9, 8, 2], [2]) == 1.0 / 3
    assert mrr([2, 8, 9], [2]) == 1.0
    assert mrr([1, 2, 3], [9]) == 0.0


def test_evaluate_retrieval_aggregate():
    # synthetic: a perfect retriever returns the relevant id first
    cases = [
        {"query": "a", "relevant_ids": [10]},
        {"query": "b", "relevant_ids": [20]},
    ]
    perfect = evaluate_retrieval(cases, retrieve=lambda c: c["relevant_ids"], k=5)
    assert isinstance(perfect, RetrievalReport)
    assert perfect.recall_at_k == 1.0 and perfect.mean_mrr == 1.0

    # a retriever that misses everything
    miss = evaluate_retrieval(cases, retrieve=lambda c: [999], k=5)
    assert miss.recall_at_k == 0.0


def test_ci_gate_threshold_example():
    # This is the shape of the CI gate: recall@k must clear a threshold.
    cases = [
        {"query": "dubai low dairy", "relevant_ids": [1]},
        {"query": "ramadan restock", "relevant_ids": [2]},
        {"query": "cold chain sop", "relevant_ids": [3]},
    ]
    # a decent retriever gets 2/3 relevant into top-k
    def retriever(c):
        return {"dubai low dairy": [1, 9], "ramadan restock": [2, 8],
                "cold chain sop": [7, 6]}[c["query"]]
    report = evaluate_retrieval(cases, retriever, k=5)
    RECALL_GATE = 0.6
    assert report.recall_at_k >= RECALL_GATE, f"recall {report.recall_at_k} below gate {RECALL_GATE}"
