"""Tests for citation_v2.database module."""

import pytest

from citation_v2.database import (
    SCHEMA_VERSION,
    get_chunks,
    get_or_create_claim,
    get_paper,
    initialize_database,
    insert_verification,
    replace_chunks,
    upsert_paper,
)


@pytest.mark.unit
class TestSchema:
    def test_schema_version(self):
        assert SCHEMA_VERSION == 1

    def test_initialize_database_idempotent(self, clean_db):
        initialize_database()
        initialize_database()

    def test_schema_version_mismatch_raises(self, clean_db):
        try:
            clean_db.execute(
                "UPDATE schema_meta SET value=? "
                "WHERE key='schema_version'",
                (str(SCHEMA_VERSION + 1),),
            )
            clean_db.commit()
            with pytest.raises(
                RuntimeError, match="schema version mismatch"
            ):
                initialize_database()
        finally:
            clean_db.execute(
                "UPDATE schema_meta SET value=? "
                "WHERE key='schema_version'",
                (str(SCHEMA_VERSION),),
            )
            clean_db.commit()

    def test_tables_exist(self, clean_db):
        tables = [
            "schema_meta",
            "papers",
            "chunks",
            "claims",
            "verifications",
        ]
        for table in tables:
            row = clean_db.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            assert row is not None


@pytest.mark.unit
class TestUpsertPaper:
    def test_insert_new_paper(self, clean_db):
        paper_id = upsert_paper(
            "arxiv:2301.12345",
            arxiv_id="2301.12345",
            source_type="arxiv",
        )
        assert paper_id > 0

    def test_get_paper_after_insert(self, clean_db):
        upsert_paper(
            "local:test.pdf",
            source_type="local_pdf",
            content_hash="a" * 64,
        )
        paper = get_paper("local:test.pdf")
        assert paper is not None
        assert paper["source_type"] == "local_pdf"

    def test_get_nonexistent_paper(self, clean_db):
        assert get_paper("nonexistent:id") is None

    def test_upsert_updates_existing(self, clean_db):
        upsert_paper(
            "test:id", content_hash="a" * 64
        )
        upsert_paper(
            "test:id",
            content_hash="b" * 64,
            source_type="updated",
        )
        paper = get_paper("test:id")
        assert paper["content_hash"] == "b" * 64
        assert paper["source_type"] == "updated"

    def test_empty_canonical_id_raises(self, clean_db):
        with pytest.raises(
            ValueError, match="cannot be empty"
        ):
            upsert_paper("")

    def test_whitespace_canonical_id_raises(self, clean_db):
        with pytest.raises(
            ValueError, match="cannot be empty"
        ):
            upsert_paper("   ")


@pytest.mark.unit
class TestClaims:
    def test_get_or_create_claim_new(self, clean_db):
        claim_id, claim_hash = get_or_create_claim(
            "This is a claim."
        )
        assert claim_id > 0
        assert len(claim_hash) == 64

    def test_get_or_create_claim_idempotent(
        self, clean_db
    ):
        cid1, hash1 = get_or_create_claim(
            "This is a claim."
        )
        cid2, hash2 = get_or_create_claim(
            "This is a claim."
        )
        assert cid1 == cid2
        assert hash1 == hash2

    def test_different_whitespace_normalized(self, clean_db):
        cid1, hash1 = get_or_create_claim(
            "  claim  with  extra  spaces  "
        )
        cid2, hash2 = get_or_create_claim(
            "claim with extra spaces"
        )
        assert cid1 == cid2
        assert hash1 == hash2

    def test_empty_claim_raises(self, clean_db):
        with pytest.raises(ValueError, match="empty"):
            get_or_create_claim("")


@pytest.mark.unit
class TestChunks:
    def test_replace_and_get_chunks(
        self, clean_db
    ):
        paper_id = upsert_paper(
            "test:chunk-paper",
            content_hash="c" * 64,
        )
        chunk_rows = [
            {
                "text": "first chunk",
                "start_char": 0,
                "end_char": 11,
                "page_start": 1,
                "page_end": 1,
                "section": None,
            },
            {
                "text": "second chunk",
                "start_char": 11,
                "end_char": 23,
                "page_start": 1,
                "page_end": 1,
                "section": None,
            },
        ]
        count = replace_chunks(
            paper_id=paper_id,
            content_hash="c" * 64,
            chunks=chunk_rows,
        )
        assert count == 2

        rows = get_chunks(
            paper_id=paper_id,
            content_hash="c" * 64,
        )
        assert len(rows) == 2
        assert rows[0]["chunk_index"] == 0
        assert rows[0]["text"] == "first chunk"
        assert rows[1]["chunk_index"] == 1

    def test_replace_chunks_replaces_old(
        self, clean_db
    ):
        paper_id = upsert_paper(
            "test:replace",
            content_hash="d" * 64,
        )
        old_chunks = [
            {
                "text": "old",
                "start_char": 0,
                "end_char": 3,
                "page_start": None,
                "page_end": None,
                "section": None,
            },
        ]
        replace_chunks(
            paper_id=paper_id,
            content_hash="d" * 64,
            chunks=old_chunks,
        )

        new_chunks = [
            {
                "text": "new1",
                "start_char": 0,
                "end_char": 4,
                "page_start": None,
                "page_end": None,
                "section": None,
            },
            {
                "text": "new2",
                "start_char": 4,
                "end_char": 8,
                "page_start": None,
                "page_end": None,
                "section": None,
            },
        ]
        replace_chunks(
            paper_id=paper_id,
            content_hash="d" * 64,
            chunks=new_chunks,
        )

        rows = get_chunks(
            paper_id=paper_id,
            content_hash="d" * 64,
        )
        assert len(rows) == 2
        assert rows[0]["text"] == "new1"

    def test_replace_chunks_empty_content_hash_raises(
        self, clean_db
    ):
        paper_id = upsert_paper(
            "test:empty-hash",
            content_hash="e" * 64,
        )
        with pytest.raises(
            ValueError, match="content_hash cannot be empty"
        ):
            replace_chunks(
                paper_id=paper_id,
                content_hash="",
                chunks=[],
            )

    def test_replace_chunks_invalid_paper_raises(
        self, clean_db
    ):
        with pytest.raises(ValueError, match="Unknown"):
            replace_chunks(
                paper_id=999999,
                content_hash="f" * 64,
                chunks=[],
            )

    def test_replace_chunks_hash_mismatch_raises(
        self, clean_db
    ):
        paper_id = upsert_paper(
            "test:hash-mismatch",
            content_hash="g" * 64,
        )
        with pytest.raises(
            ValueError, match="content_hash does not match"
        ):
            replace_chunks(
                paper_id=paper_id,
                content_hash="h" * 64,
                chunks=[],
            )

    def test_replace_chunks_empty_text_raises(
        self, clean_db
    ):
        paper_id = upsert_paper(
            "test:empty-text",
            content_hash="i" * 64,
        )
        chunks = [
            {
                "text": "",
                "start_char": 0,
                "end_char": 0,
                "page_start": None,
                "page_end": None,
                "section": None,
            },
        ]
        with pytest.raises(
            ValueError, match="empty text"
        ):
            replace_chunks(
                paper_id=paper_id,
                content_hash="i" * 64,
                chunks=chunks,
            )

    def test_get_chunks_filters_by_hash(
        self, clean_db
    ):
        paper_id = upsert_paper(
            "test:filter",
            content_hash="j" * 64,
        )
        chunks = [
            {
                "text": "chunk text",
                "start_char": 0,
                "end_char": 10,
                "page_start": None,
                "page_end": None,
                "section": None,
            },
        ]
        replace_chunks(
            paper_id=paper_id,
            content_hash="j" * 64,
            chunks=chunks,
        )

        rows = get_chunks(
            paper_id=paper_id,
            content_hash="different" * 13,
        )
        assert rows == []


@pytest.mark.unit
class TestVerifications:
    def test_insert_verification_pass(
        self, clean_db
    ):
        paper_id = upsert_paper(
            "test:verify-pass",
            content_hash="k" * 64,
        )
        claim_id, _ = get_or_create_claim("test claim")
        vid = insert_verification(
            claim_id=claim_id,
            paper_id=paper_id,
            verdict="PASS",
            provenance_verified=True,
        )
        assert vid > 0

    def test_insert_verification_warn(
        self, clean_db
    ):
        paper_id = upsert_paper(
            "test:verify-warn",
            content_hash="l" * 64,
        )
        claim_id, _ = get_or_create_claim("warn claim")
        vid = insert_verification(
            claim_id=claim_id,
            paper_id=paper_id,
            verdict="WARN",
            provenance_verified=False,
        )
        assert vid > 0

    def test_insert_pass_without_provenance_raises(
        self, clean_db
    ):
        paper_id = upsert_paper(
            "test:verify-fail",
            content_hash="m" * 64,
        )
        claim_id, _ = get_or_create_claim("fail claim")
        with pytest.raises(
            ValueError, match="PASS is forbidden"
        ):
            insert_verification(
                claim_id=claim_id,
                paper_id=paper_id,
                verdict="PASS",
                provenance_verified=False,
            )

    def test_invalid_verdict_raises(
        self, clean_db
    ):
        paper_id = upsert_paper(
            "test:invalid",
            content_hash="n" * 64,
        )
        claim_id, _ = get_or_create_claim("x")
        with pytest.raises(
            ValueError, match="Invalid verdict"
        ):
            insert_verification(
                claim_id=claim_id,
                paper_id=paper_id,
                verdict="INVALID",
                provenance_verified=False,
            )

    def test_score_validation(
        self, clean_db
    ):
        paper_id = upsert_paper(
            "test:scores",
            content_hash="o" * 64,
        )
        claim_id, _ = get_or_create_claim("scores")
        with pytest.raises(
            ValueError, match="between 0 and 1"
        ):
            insert_verification(
                claim_id=claim_id,
                paper_id=paper_id,
                verdict="WARN",
                provenance_verified=False,
                entailment_score=1.5,
            )

    def test_end_before_start_raises(
        self, clean_db
    ):
        paper_id = upsert_paper(
            "test:offsets",
            content_hash="p" * 64,
        )
        claim_id, _ = get_or_create_claim("offsets")
        with pytest.raises(
            ValueError,
            match="greater than start",
        ):
            insert_verification(
                claim_id=claim_id,
                paper_id=paper_id,
                verdict="WARN",
                provenance_verified=False,
                evidence_start_char=10,
                evidence_end_char=5,
            )

    def test_verdict_uppercased(
        self, clean_db
    ):
        paper_id = upsert_paper(
            "test:case",
            content_hash="q" * 64,
        )
        claim_id, _ = get_or_create_claim("case")
        insert_verification(
            claim_id=claim_id,
            paper_id=paper_id,
            verdict="warn",
            provenance_verified=False,
        )
        get_paper("test:case")
        row = clean_db.execute(
            "SELECT verdict FROM verifications "
            "WHERE claim_id=? ORDER BY id DESC LIMIT 1",
            (claim_id,),
        ).fetchone()
        assert row["verdict"] == "WARN"


@pytest.mark.unit
class TestDatabaseSummary:
    def test_summary_returns_counts(self, clean_db):
        from citation_v2.database import database_summary

        summary = database_summary()
        for key in (
            "papers",
            "chunks",
            "claims",
            "verifications",
            "bibliography_runs",
        ):
            assert key in summary
            assert summary[key] >= 0
