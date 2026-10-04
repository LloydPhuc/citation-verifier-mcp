# Known Limitations

## Source Types

| Source Type | Status | Details |
|---|---|---|
| DOI full-text resolution | **Not implemented** | DOIs are not currently resolved to full text. Claims citing DOI-only sources return `ABSTAIN`. |
| Title/author → reference resolution | **Not implemented** | The system cannot look up a paper by title or author alone. Must provide arXiv ID, URL, or local file. |
| URL full-text extraction | **Partial** | Works for directly accessible PDFs. Does not render JavaScript-heavy pages or resolve paywalled content. |
| Plain text / BibTeX / LaTeX as V2 full text | **Not supported** | Claim tools require a local PDF, arXiv identifier/URL or direct PDF URL. V1 bibliography files are handled separately by RefChecker. |

## Semantic Verification

| Limitation | Status | Details |
|---|---|---|
| Numerical claims | **Guarded, not inferred** | Numbers in claims must appear exactly in evidence. Semantic NLI scores alone are not trusted for numeric claims. |
| Approximate matching | **Not available** | Provenance is exact character matching only. Paraphrased or reformatted quotes will fail verification. |
| Multi-document verification | **Not supported** | Each claim is verified against a single source. Cross-source evidence synthesis is not available. |
| Fact-checking scope | **Single claim** | The system verifies whether a source supports a claim. It does not validate the claim against external knowledge. |
| Lexical coverage is a heuristic | **By design** | The relevance gate uses claim-word coverage (fraction of claim content-word stems found in evidence) to filter strong contradiction candidates. This is a lexical heuristic, not a semantic similarity measure. |
| Coverage threshold | **Heuristic** | The threshold is `0.30` (≥30% of claim content-word stems must appear in evidence). It was chosen to satisfy Cases A–D and has **not** been calibrated on a broader benchmark corpus. May need adjustment for claims of different lengths. |
| Synonym-based contradictions | **Accepted risk** | Genuine contradictions with no shared stems are filtered out and may produce `ABSTAIN` when no other signal remains. A true contradiction may be missed; the gate does not guarantee the absence of false verdicts. |
| Custom stemmer | **Simplified** | The stemmer is a lightweight suffix-stripping implementation (three-stage: plurals, verb endings, derivational suffixes). It is **not** a full Porter stemmer and does **not** handle all morphological variants. It normalizes high-frequency cases (e.g., *hallucinated* ≡ *hallucinations*, *citations* ≡ *citation*). |
| ASCII-only tokenization | **Known limitation** | Content-word extraction uses `[a-zA-Z]+`; non-ASCII letters and digits are excluded, and hyphens split compounds into separate tokens. Scientific terms may not be fully captured. |
| NLI score variability | **Not a guarantee** | NLI scores may vary across environments (different `transformers` versions, model cache state). Verdicts may differ between runs. Scores are probabilistic, not guaranteed correct. |
| No benchmark accuracy | **Not established** | The system has **not** been evaluated for benchmark-wide accuracy on a large corpus. The 0.30 threshold and the relevance gate are heuristics validated against a small set of real-source cases (Cases A–F), not a systematic benchmark. |

## Performance

| Limitation | Status | Details |
|---|---|---|
| RefChecker (V1) runtime | **Inherent** | The `citation_summary` tool invokes `academic-refchecker.exe` which takes ~5–6 minutes for 24 references. The application has a 600s timeout. External runners (CI/CD, Task tool wrappers) must allow ≥12 minutes. |
| Setup model download | **One-time** | Initial download of `cross-encoder/nli-deberta-v3-small` (~170 MB) requires internet access. Runtime loads cached model/tokenizer files only; missing cache requires successful setup preparation. |
| BM25 index rebuild | **Per session** | BM25 indexes are rebuilt per verification session. SQLite caching avoids re-chunking but does not cache the BM25 index in memory. |
| Batch size | **Capped** | Maximum 100 items per batch (`MAX_BATCH_ITEMS`). |

## Platform & Dependencies

| Limitation | Status | Details |
|---|---|---|
| Linux/macOS | **Untested** | Windows 11 is historically tested; Windows 10 is not independently verified. Scripts use PowerShell. Some path handling may not work on Unix. |
| GPU acceleration | **Not used** | PyTorch CPU-only build. No CUDA support compiled in. |
| GROBID dependency | **External V1 dependency** | All three V1 tools (`verify_document`, `verify_bibliography`, `citation_summary`) invoke RefChecker and require GROBID when execution needs PDF parsing. V2 (`verify_claim`, `verify_claims`) does not require GROBID. |
| Python version | **3.13+ required** | Only Python 3.13.7 has been independently verified. Bootstrap script prefers 3.13 via `py` launcher. |
| Windows temp permissions | **Workaround needed** | Default pytest temp directory (`C:\Users\...\AppData\Local\Temp\pytest-of-user`) may have permission issues. Use `--basetemp=<writable>` when running tests. |

## Verdict Limitations

| Limitation | Status | Details |
|---|---|---|
| `ABSTAIN` ≠ false | **Fundamental** | `ABSTAIN` means the system could not verify the claim from the source. It does not mean the claim is false. |
| Provenance ambiguity | **Context-dependent** | Quote-location searches can reject multiple occurrences when uniqueness is required. The V2 pipeline verifies supplied exact spans; repeated text alone does not invalidate a known span. |
| Context window limits | **Fixed** | NLI model processes evidence windows of 1600 characters. Longer contexts are truncated. |
| Threshold rigidity | **By design** | Strong entailment/contradiction cutoffs default to 0.70 and are configurable through environment variables. Moderate cutoff 0.50 and relevance coverage 0.30 are code constants. |

## Caching Limitations

| Limitation | Status | Details |
|---|---|---|
| Cache persistence | **File-based** | Raw and normalized text are cached on disk. Cache corruption can cause verification failures. |
| Cache TTL | **Time-based only** | Expired cache entries are not proactively cleaned. Manual cleanup may be needed. |
| Database schema | **Versioned** | Schema version must match code version. A mismatch raises `RuntimeError` on startup. |
