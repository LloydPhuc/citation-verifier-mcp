"""Single and batch calls must use one grounded verification implementation."""

from dataclasses import replace

import pytest

from citation_v2 import batch, database, verifier
from citation_v2.policy import EvidenceCandidate
from citation_v2.schemas import verification_result_to_response
from citation_v2.source_loader import SourceDocument
from citation_v2.text_extractor import ExtractedPage


@pytest.fixture
def prepared(monkeypatch):
    text = "The study reports 15 samples."
    source = SourceDocument(
        source_input="sample.pdf",
        canonical_id="local:sample",
        source_type="local_pdf",
        source_state="FULL_TEXT",
        paper_id=1,
        text=text,
        content_hash="a" * 64,
        normalized_text_path="sample.txt",
        pages=[ExtractedPage(1, text, 0, len(text))],
        cache_hit=False,
    )
    row = {
        "id": 1,
        "chunk_index": 0,
        "text": text,
        "start_char": 0,
        "end_char": len(text),
        "page_start": 1,
        "page_end": 1,
        "section": None,
        "content_hash": source.content_hash,
    }
    for module in (verifier, batch):
        monkeypatch.setattr(module, "load_source", lambda _: source)
        monkeypatch.setattr(module, "_load_or_create_chunks", lambda _: [row])
    return EvidenceCandidate(
        bm25_rank=1,
        bm25_score=1.0,
        chunk_id=1,
        chunk_index=0,
        quote=text,
        start_char=0,
        end_char=len(text),
        page_start=1,
        page_end=1,
        entailment=0.95,
        contradiction=0.02,
        neutral=0.03,
        predicted_label="entailment",
        premise_truncated=False,
        provenance_verified=True,
        numeric_match=True,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, "PASS"),
        ({"numeric_match": False}, "WARN"),
        ({"entailment": 0.01, "contradiction": 0.98}, "FAIL"),
        ({"provenance_verified": False}, "ABSTAIN"),
        ({"entailment": 0.01, "contradiction": 0.98, "claim_relevant": False}, "ABSTAIN"),
    ],
)
def test_single_and_batch_have_identical_results(prepared, monkeypatch, changes, expected):
    candidate = replace(prepared, **changes)
    monkeypatch.setattr(verifier, "_score_candidates", lambda *a, **kw: [candidate])
    single = verifier.verify_claim("study reports 15 samples", "sample.pdf", persist=False)
    grouped = batch.verify_claims_batch(
        [{"claim": "study reports 15 samples", "source": "sample.pdf"}],
        persist=False,
    )["results"][0]
    assert grouped.pop("index") == 0
    assert single.verdict == expected
    assert grouped == verification_result_to_response(single, top_k=5)


@pytest.mark.unit
@pytest.mark.parametrize("retrieved", [False, True])
def test_empty_candidates_are_not_confused_with_no_retrieval(prepared, monkeypatch, retrieved):
    class Retriever:
        def search(self, claim, top_k):
            return [object()] if retrieved else []

    monkeypatch.setattr(verifier, "_score_candidates", lambda *a, **kw: [])
    calls = []
    monkeypatch.setattr(verifier, "_persist_result", lambda *a, **kw: calls.append(kw) or 7)
    result = verifier.verify_prepared_claim(
        claim="study",
        source_input="sample.pdf",
        source=verifier.load_source("sample.pdf"),
        rows=[],
        retriever=Retriever(),
        top_k=5,
        persist=True,
    )
    assert result.verdict == "ABSTAIN"
    assert result.reason == ("NO_EVIDENCE_WINDOWS" if retrieved else "NO_LEXICAL_CANDIDATES")
    assert result.model_id is None
    assert result.verification_id == 7
    assert len(calls) == 1
    assert calls[0]["model_id"] is None


@pytest.mark.unit
def test_configured_model_identity_is_used_everywhere(prepared, monkeypatch):
    monkeypatch.setattr(verifier, "NLI_MODEL_ID", "configured-model")
    monkeypatch.setattr(verifier, "_score_candidates", lambda *a, **kw: [prepared])
    calls = []
    monkeypatch.setattr(verifier, "_persist_result", lambda *a, **kw: calls.append(kw) or 11)
    result = verifier.verify_claim("study reports 15 samples", "sample.pdf")
    assert result.model_id == "configured-model"
    assert calls[0]["model_id"] == result.model_id


@pytest.mark.unit
@pytest.mark.parametrize("reader", ["paper", "chunks", "summary"])
def test_database_read_helpers_close_connection(monkeypatch, reader):
    import sqlite3

    database.initialize_database()
    open_connection = database.get_connection
    connections = []

    def tracked_connection():
        conn = open_connection()
        connections.append(conn)
        return conn

    monkeypatch.setattr(database, "get_connection", tracked_connection)
    try:
        if reader == "paper":
            database.get_paper("absent")
        elif reader == "chunks":
            database.get_chunks(paper_id=99999, content_hash="0" * 64)
        else:
            database.database_summary()
        assert connections
        for conn in connections:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                conn.execute("SELECT 1")
    finally:
        for conn in connections:
            conn.close()
