# Known Limitations

## Source Types

| Source Type | Status | Details |
|---|---|---|
| DOI full-text resolution | **Not implemented** | DOIs are not currently resolved to full text. Claims citing DOI-only sources return `ABSTAIN`. |
| Title/author → reference resolution | **Not implemented** | The system cannot look up a paper by title or author alone. Must provide arXiv ID, URL, or local file. |
| URL full-text extraction | **Partial** | Works for directly accessible PDFs. Does not render JavaScript-heavy pages or resolve paywalled content. |
| Plain text sources | **Supported** | Any string is treated as raw text. No citation extraction is performed on plain text. |

## Semantic Verification

| Limitation | Status | Details |
|---|---|---|
| Numerical claims | **Guarded, not inferred** | Numbers in claims must appear exactly in evidence. Semantic NLI scores alone are not trusted for numeric claims. |
| Approximate matching | **Not available** | Provenance is exact character matching only. Paraphrased or reformatted quotes will fail verification. |
| Multi-document verification | **Not supported** | Each claim is verified against a single source. Cross-source evidence synthesis is not available. |
| Fact-checking scope | **Single claim** | The system verifies whether a source supports a claim. It does not validate the claim against external knowledge. |

## Performance

| Limitation | Status | Details |
|---|---|---|
| RefChecker (V1) runtime | **Inherent** | The `citation_summary` tool invokes `academic-refchecker.exe` which takes ~5–6 minutes for 24 references. The application has a 600s timeout. External runners (CI/CD, Task tool wrappers) must allow ≥12 minutes. |
| First-run model download | **One-time** | Initial download of `cross-encoder/nli-deberta-v3-small` (~170 MB) requires internet access. Subsequent runs use the local cache. |
| BM25 index rebuild | **Per session** | BM25 indexes are rebuilt per verification session. SQLite caching avoids re-chunking but does not cache the BM25 index in memory. |
| Batch size | **Capped** | Maximum 100 items per batch (`MAX_BATCH_ITEMS`). |

## Platform & Dependencies

| Limitation | Status | Details |
|---|---|---|
| Linux/macOS | **Untested** | The project targets Windows 10/11. Scripts use PowerShell. Some path handling may not work on Unix. |
| GPU acceleration | **Not used** | PyTorch CPU-only build. No CUDA support compiled in. |
| GROBID dependency | **Optional** | GROBID is used for advanced citation parsing in V1 (`citation_summary`). V2 pipeline (`verify_claim`, `verify_claims`) does not require GROBID. |
| Python version | **3.13+ required** | Only Python 3.13.7 has been independently verified. Bootstrap script prefers 3.13 via `py` launcher. |
| Windows temp permissions | **Workaround needed** | Default pytest temp directory (`C:\Users\...\AppData\Local\Temp\pytest-of-user`) may have permission issues. Use `--basetemp=<writable>` when running tests. |

## Verdict Limitations

| Limitation | Status | Details |
|---|---|---|
| `ABSTAIN` ≠ false | **Fundamental** | `ABSTAIN` means the system could not verify the claim from the source. It does not mean the claim is false. |
| Provenance ambiguity | **Conservative** | Quotes occurring multiple times in the source are treated as ambiguous and fail provenance verification. |
| Context window limits | **Fixed** | NLI model processes evidence windows of 1600 characters. Longer contexts are truncated. |
| Threshold rigidity | **By design** | Thresholds (0.70 entailment/contradiction, 0.50 moderate) are fixed by default. They can be tuned via environment variables. |

## Caching Limitations

| Limitation | Status | Details |
|---|---|---|
| Cache persistence | **File-based** | Raw and normalized text are cached on disk. Cache corruption can cause verification failures. |
| Cache TTL | **Time-based only** | Expired cache entries are not proactively cleaned. Manual cleanup may be needed. |
| Database schema | **Versioned** | Schema version must match code version. A mismatch raises `RuntimeError` on startup. |
