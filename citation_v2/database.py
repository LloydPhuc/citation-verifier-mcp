from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Sequence

from .config import (
    DB_PATH,
    PIPELINE_VERSION,
    SQLITE_BUSY_TIMEOUT_MS,
    initialize_runtime_paths,
)


SCHEMA_VERSION = 1


# ============================================================
# Helpers
# ============================================================

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(text: str) -> str:
    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


def _clean_optional_string(
    value: str | None,
) -> str | None:
    if value is None:
        return None

    value = value.strip()

    return value if value else None


# ============================================================
# Connection handling
# ============================================================

def get_connection() -> sqlite3.Connection:
    """
    Open a configured SQLite connection.

    A new connection is returned for each call.
    """

    initialize_runtime_paths()

    conn = sqlite3.connect(
        DB_PATH,
        timeout=SQLITE_BUSY_TIMEOUT_MS / 1000.0,
    )

    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute(
        f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS};"
    )

    return conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """
    Atomic write transaction.

    BEGIN IMMEDIATE prevents two writers from silently
    interleaving a multi-step operation.
    """

    conn = get_connection()

    try:
        conn.execute("BEGIN IMMEDIATE;")

        yield conn

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


# ============================================================
# Schema initialization
# ============================================================

def initialize_database() -> None:
    """
    Initialize the database schema.

    Safe to call repeatedly.
    """

    with transaction() as conn:

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );


            CREATE TABLE IF NOT EXISTS papers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                canonical_id TEXT NOT NULL UNIQUE,

                doi TEXT,
                arxiv_id TEXT,

                title TEXT,
                authors_json TEXT,

                year INTEGER,
                venue TEXT,

                canonical_url TEXT,
                source_type TEXT,

                content_hash TEXT,
                normalized_text_path TEXT,

                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );


            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                paper_id INTEGER NOT NULL,
                content_hash TEXT NOT NULL,

                chunk_index INTEGER NOT NULL,

                text TEXT NOT NULL,

                start_char INTEGER NOT NULL,
                end_char INTEGER NOT NULL,

                page_start INTEGER,
                page_end INTEGER,

                section TEXT,

                created_at TEXT NOT NULL,

                FOREIGN KEY (paper_id)
                    REFERENCES papers(id)
                    ON DELETE CASCADE,

                UNIQUE (
                    paper_id,
                    content_hash,
                    chunk_index
                )
            );


            CREATE TABLE IF NOT EXISTS claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                claim_hash TEXT NOT NULL UNIQUE,
                claim_text TEXT NOT NULL,

                created_at TEXT NOT NULL
            );


            CREATE TABLE IF NOT EXISTS verifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                claim_id INTEGER NOT NULL,
                paper_id INTEGER NOT NULL,

                source_content_hash TEXT,

                verdict TEXT NOT NULL,
                semantic_class TEXT,

                entailment_score REAL,
                contradiction_score REAL,
                neutral_score REAL,

                best_chunk_id INTEGER,

                evidence_quote TEXT,

                evidence_start_char INTEGER,
                evidence_end_char INTEGER,

                provenance_verified INTEGER NOT NULL,

                model_id TEXT,
                pipeline_version TEXT NOT NULL,

                created_at TEXT NOT NULL,

                FOREIGN KEY (claim_id)
                    REFERENCES claims(id)
                    ON DELETE CASCADE,

                FOREIGN KEY (paper_id)
                    REFERENCES papers(id)
                    ON DELETE CASCADE,

                FOREIGN KEY (best_chunk_id)
                    REFERENCES chunks(id)
                    ON DELETE SET NULL
            );


            CREATE TABLE IF NOT EXISTS bibliography_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                source TEXT NOT NULL,

                total_references INTEGER,
                total_errors INTEGER,
                total_warnings INTEGER,
                total_unverified INTEGER,

                health TEXT,

                report_json TEXT,

                created_at TEXT NOT NULL
            );


            CREATE INDEX IF NOT EXISTS idx_papers_doi
            ON papers(doi);


            CREATE INDEX IF NOT EXISTS idx_papers_arxiv
            ON papers(arxiv_id);


            CREATE INDEX IF NOT EXISTS idx_chunks_paper_hash
            ON chunks(
                paper_id,
                content_hash
            );


            CREATE INDEX IF NOT EXISTS idx_verifications_claim
            ON verifications(claim_id);


            CREATE INDEX IF NOT EXISTS idx_verifications_paper
            ON verifications(paper_id);


            CREATE INDEX IF NOT EXISTS idx_verifications_pipeline
            ON verifications(
                pipeline_version,
                model_id
            );
            """
        )

        row = conn.execute(
            """
            SELECT value
            FROM schema_meta
            WHERE key = 'schema_version'
            """
        ).fetchone()

        if row is None:

            conn.execute(
                """
                INSERT INTO schema_meta(
                    key,
                    value
                )
                VALUES(
                    'schema_version',
                    ?
                )
                """,
                (str(SCHEMA_VERSION),),
            )

        else:

            current_version = int(row["value"])

            if current_version != SCHEMA_VERSION:
                raise RuntimeError(
                    "Database schema version mismatch: "
                    f"database={current_version}, "
                    f"code={SCHEMA_VERSION}. "
                    "A migration is required."
                )


# ============================================================
# Papers
# ============================================================

def upsert_paper(
    canonical_id: str,
    *,
    doi: str | None = None,
    arxiv_id: str | None = None,
    title: str | None = None,
    authors: Sequence[str] | None = None,
    year: int | None = None,
    venue: str | None = None,
    canonical_url: str | None = None,
    source_type: str | None = None,
    content_hash: str | None = None,
    normalized_text_path: str | None = None,
) -> int:

    canonical_id = canonical_id.strip()

    if not canonical_id:
        raise ValueError(
            "canonical_id cannot be empty."
        )

    doi = _clean_optional_string(doi)
    arxiv_id = _clean_optional_string(arxiv_id)
    title = _clean_optional_string(title)
    venue = _clean_optional_string(venue)
    canonical_url = _clean_optional_string(
        canonical_url
    )
    source_type = _clean_optional_string(
        source_type
    )
    content_hash = _clean_optional_string(
        content_hash
    )
    normalized_text_path = _clean_optional_string(
        normalized_text_path
    )

    authors_json = None

    if authors is not None:
        authors_json = json.dumps(
            list(authors),
            ensure_ascii=False,
        )

    now = utc_now()

    with transaction() as conn:

        conn.execute(
            """
            INSERT INTO papers (
                canonical_id,
                doi,
                arxiv_id,
                title,
                authors_json,
                year,
                venue,
                canonical_url,
                source_type,
                content_hash,
                normalized_text_path,
                created_at,
                updated_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?
            )

            ON CONFLICT(canonical_id)
            DO UPDATE SET

                doi =
                    COALESCE(
                        excluded.doi,
                        papers.doi
                    ),

                arxiv_id =
                    COALESCE(
                        excluded.arxiv_id,
                        papers.arxiv_id
                    ),

                title =
                    COALESCE(
                        excluded.title,
                        papers.title
                    ),

                authors_json =
                    COALESCE(
                        excluded.authors_json,
                        papers.authors_json
                    ),

                year =
                    COALESCE(
                        excluded.year,
                        papers.year
                    ),

                venue =
                    COALESCE(
                        excluded.venue,
                        papers.venue
                    ),

                canonical_url =
                    COALESCE(
                        excluded.canonical_url,
                        papers.canonical_url
                    ),

                source_type =
                    COALESCE(
                        excluded.source_type,
                        papers.source_type
                    ),

                content_hash =
                    COALESCE(
                        excluded.content_hash,
                        papers.content_hash
                    ),

                normalized_text_path =
                    COALESCE(
                        excluded.normalized_text_path,
                        papers.normalized_text_path
                    ),

                updated_at =
                    excluded.updated_at
            """,
            (
                canonical_id,
                doi,
                arxiv_id,
                title,
                authors_json,
                year,
                venue,
                canonical_url,
                source_type,
                content_hash,
                normalized_text_path,
                now,
                now,
            ),
        )

        row = conn.execute(
            """
            SELECT id
            FROM papers
            WHERE canonical_id = ?
            """,
            (canonical_id,),
        ).fetchone()

        if row is None:
            raise RuntimeError(
                "Paper upsert succeeded but "
                "paper could not be reloaded."
            )

        return int(row["id"])


def get_paper(
    canonical_id: str,
) -> dict[str, Any] | None:

    canonical_id = canonical_id.strip()

    with get_connection() as conn:

        row = conn.execute(
            """
            SELECT *
            FROM papers
            WHERE canonical_id = ?
            """,
            (canonical_id,),
        ).fetchone()

    if row is None:
        return None

    result = dict(row)

    raw_authors = result.pop(
        "authors_json",
        None,
    )

    if raw_authors:

        try:
            result["authors"] = json.loads(
                raw_authors
            )

        except json.JSONDecodeError:
            result["authors"] = []

    else:
        result["authors"] = []

    return result


# ============================================================
# Chunks
# ============================================================

def replace_chunks(
    *,
    paper_id: int,
    content_hash: str,
    chunks: Sequence[dict[str, Any]],
) -> int:
    """
    Atomically replace chunks for one exact
    paper + content version.
    """

    if not content_hash.strip():
        raise ValueError(
            "content_hash cannot be empty."
        )

    with transaction() as conn:
        paper = conn.execute(
            """
            SELECT id, content_hash
            FROM papers
            WHERE id = ?
            """,
            (paper_id,),
        ).fetchone()

        if paper is None:
            raise ValueError(
                f"Unknown paper_id: {paper_id}"
            )

        current_hash = paper["content_hash"]

        if not current_hash:
            raise ValueError(
                "Paper has no current content_hash."
            )

        if current_hash != content_hash:
            raise ValueError(
                "Chunk content_hash does not match "
                "the paper's current content version."
            )

        conn.execute(
            """
            DELETE FROM chunks
            WHERE
                paper_id = ?
                AND content_hash = ?
            """,
            (
                paper_id,
                content_hash,
            ),
        )

        now = utc_now()

        for expected_index, chunk in enumerate(chunks):
            text = str(
                chunk.get("text", "")
            )

            if not text:
                raise ValueError(
                    f"Chunk {expected_index} "
                    "has empty text."
                )

            start_char = int(
                chunk["start_char"]
            )

            end_char = int(
                chunk["end_char"]
            )

            if start_char < 0:
                raise ValueError(
                    "start_char cannot be negative."
                )

            if end_char <= start_char:
                raise ValueError(
                    "end_char must be greater "
                    "than start_char."
                )

            conn.execute(
                """
                INSERT INTO chunks (
                    paper_id,
                    content_hash,
                    chunk_index,
                    text,
                    start_char,
                    end_char,
                    page_start,
                    page_end,
                    section,
                    created_at
                )
                VALUES (
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?
                )
                """,
                (
                    paper_id,
                    content_hash,
                    expected_index,
                    text,
                    start_char,
                    end_char,
                    chunk.get("page_start"),
                    chunk.get("page_end"),
                    chunk.get("section"),
                    now,
                ),
            )

        return len(chunks)

def get_chunks(
    *,
    paper_id: int,
    content_hash: str,
) -> list[dict[str, Any]]:

    with get_connection() as conn:

        rows = conn.execute(
            """
            SELECT *
            FROM chunks
            WHERE
                paper_id = ?
                AND content_hash = ?
            ORDER BY chunk_index
            """,
            (
                paper_id,
                content_hash,
            ),
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


# ============================================================
# Claims
# ============================================================

def get_or_create_claim(
    claim_text: str,
) -> tuple[int, str]:

    normalized_claim = " ".join(
        claim_text.split()
    )

    if not normalized_claim:
        raise ValueError(
            "claim_text cannot be empty."
        )

    claim_hash = sha256_text(
        normalized_claim
    )

    with transaction() as conn:

        conn.execute(
            """
            INSERT INTO claims (
                claim_hash,
                claim_text,
                created_at
            )
            VALUES (?, ?, ?)

            ON CONFLICT(claim_hash)
            DO NOTHING
            """,
            (
                claim_hash,
                normalized_claim,
                utc_now(),
            ),
        )

        row = conn.execute(
            """
            SELECT id
            FROM claims
            WHERE claim_hash = ?
            """,
            (claim_hash,),
        ).fetchone()

        if row is None:
            raise RuntimeError(
                "Claim could not be created "
                "or retrieved."
            )

        return (
            int(row["id"]),
            claim_hash,
        )


# ============================================================
# Verification persistence
# ============================================================

def insert_verification(
    *,
    claim_id: int,
    paper_id: int,
    verdict: str,
    provenance_verified: bool,
    source_content_hash: str | None = None,
    semantic_class: str | None = None,
    entailment_score: float | None = None,
    contradiction_score: float | None = None,
    neutral_score: float | None = None,
    best_chunk_id: int | None = None,
    evidence_quote: str | None = None,
    evidence_start_char: int | None = None,
    evidence_end_char: int | None = None,
    model_id: str | None = None,
    pipeline_version: str = PIPELINE_VERSION,
) -> int:

    verdict = verdict.strip().upper()

    allowed_verdicts = {
        "PASS",
        "WARN",
        "FAIL",
        "ABSTAIN",
    }

    if verdict not in allowed_verdicts:
        raise ValueError(
            f"Invalid verdict: {verdict}"
        )

    if (
        verdict == "PASS"
        and not provenance_verified
    ):
        raise ValueError(
            "PASS is forbidden when "
            "provenance_verified is false."
        )

    for name, score in (
        ("entailment_score", entailment_score),
        (
            "contradiction_score",
            contradiction_score,
        ),
        ("neutral_score", neutral_score),
    ):
        if score is not None:
            if not 0.0 <= float(score) <= 1.0:
                raise ValueError(
                    f"{name} must be between "
                    "0 and 1."
                )

    if (
        evidence_start_char is not None
        and evidence_end_char is not None
        and evidence_end_char
        <= evidence_start_char
    ):
        raise ValueError(
            "Evidence end offset must be "
            "greater than start offset."
        )

    with transaction() as conn:

        cursor = conn.execute(
            """
            INSERT INTO verifications (
                claim_id,
                paper_id,
                source_content_hash,
                verdict,
                semantic_class,
                entailment_score,
                contradiction_score,
                neutral_score,
                best_chunk_id,
                evidence_quote,
                evidence_start_char,
                evidence_end_char,
                provenance_verified,
                model_id,
                pipeline_version,
                created_at
            )
            VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?
            )
            """,
            (
                claim_id,
                paper_id,
                source_content_hash,
                verdict,
                semantic_class,
                entailment_score,
                contradiction_score,
                neutral_score,
                best_chunk_id,
                evidence_quote,
                evidence_start_char,
                evidence_end_char,
                1 if provenance_verified else 0,
                model_id,
                pipeline_version,
                utc_now(),
            ),
        )

        return int(cursor.lastrowid)


# ============================================================
# Diagnostics
# ============================================================

def database_summary() -> dict[str, int]:

    initialize_database()

    tables = (
        "papers",
        "chunks",
        "claims",
        "verifications",
        "bibliography_runs",
    )

    result: dict[str, int] = {}

    with get_connection() as conn:

        for table in tables:

            row = conn.execute(
                f"SELECT COUNT(*) AS n "
                f"FROM {table}"
            ).fetchone()

            result[table] = int(
                row["n"]
            )

    return result