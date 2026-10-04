# Verdicts Guide

## Verdict Summary

| Verdict | Semantic Class | Confidence Gate | When It's Returned |
|---|---|---|---|
| `PASS` | `SUPPORTED` | High entailment + provenance | Strong NLI entailment (≥0.70) with verified provenance and numeric match |
| `WARN` | `CONFLICTING_EVIDENCE` | Mixed signals | Provenance-verified strong entailment and relevant strong contradiction, unless contradiction dominance applies |
| `WARN` | `PARTIALLY_SUPPORTED` | Moderate support / numeric mismatch | Moderate entailment with provenance, or strong entailment with numeric mismatch |
| `FAIL` | `CONTRADICTED` | High contradiction + provenance + relevance | Strong NLI contradiction (≥0.70), verified provenance and claim-word coverage ≥0.30 |
| `ABSTAIN` | `INSUFFICIENT_EVIDENCE` | No strong signal | No evidence windows, no lexical candidates, or NLI below all thresholds |
| `ABSTAIN` | `INSUFFICIENT_EVIDENCE` | Infrastructure | Unsupported/unavailable source; specific status appears in `source_state` and `reason` |

## Critical Rules

1. **`PASS` is forbidden without `provenance_verified == true`.** The batch processor enforces this as a final boundary check. Any ungrounded `PASS` is downgraded to `ABSTAIN` with reason `PASS_BLOCKED_BY_PROVENANCE_GATE`.

2. **Numeric claims must match exactly.** If the claim contains explicit numbers (detected via regex), every number must also appear in the evidence quote. Semantic NLI alone cannot verify numbers. A strong entailment with numeric mismatch → `WARN` with reason `NUMERIC_VALUE_NOT_VERIFIED`.

3. **Infrastructure failures → `ABSTAIN`, never `FAIL`.** A network timeout, unsupported source, or extraction error does not constitute evidence that the claim is false. It is always reported as `ABSTAIN`.

4. **Scores are separated from verdicts.** NLI scores (entailment, contradiction, neutral) are reported alongside the verdict but do not independently determine it. The decision policy applies explicit thresholds.

5. **Retrieval relevance is primary.** BM25 rank is the first ordering signal when selecting the best evidence candidate. NLI is the semantic gate, not the relevance signal.

## Decision Policy (Ordered)

The `_decide()` function in `verifier.py` applies these steps in order. The first matching step determines the verdict. Strong-score cutoffs below are defaults configurable through environment variables; coverage 0.30 and moderate cutoff 0.50 are code constants.

### Step 1: No Candidates → ABSTAIN

```
No evidence windows produced
  → ABSTAIN / INSUFFICIENT_EVIDENCE / NO_EVIDENCE_WINDOWS
```

### Step 2: Conflicting Strong Evidence → WARN

If **both** strong entailments (≥0.70) and relevance-gated strong contradictions (≥0.70) exist with verified provenance:

- **Contradictions dominate** (≥3× more contradictions than entailments, and max contradiction exceeds max entailment + 0.15):
  - → `ABSTAIN` / `INSUFFICIENT_EVIDENCE` / `CONTRADICTIONS_DOMINATE_ENTAILMENT_SIGNAL`
  - Rationale: the "entailment" signal is likely spurious NLI confusion on an unrelated claim.

- **Otherwise**:
  - → `WARN` / `CONFLICTING_EVIDENCE` / `STRONG_ENTAILMENT_AND_CONTRADICTION`

### Step 3: Strong Contradiction Only → FAIL

A strong NLI contradiction score alone is **insufficient** for a `FAIL` verdict.

If only strong contradictions (≥0.70) exist **with verified provenance** **and** the evidence passes the **topical relevance gate**:

- → `FAIL` / `CONTRADICTED` / `STRONG_CONTRADICTION`

If the evidence fails the relevance gate (no meaningful content-word overlap with the claim), the contradiction is treated as an NLI artifact of semantic distance, not logical contradiction:

- → That contradiction is excluded; remaining evidence can still produce support or conflict. If no eligible signal remains, Step 6 returns `ABSTAIN`.

**Relevance gate details:** See [Evidence Relevance Gate](#evidence-relevance-gate) below.

#### Evidence Relevance Gate

The relevance gate filters strong contradiction candidates based on topical overlap between the claim and the evidence passage:

1. **Content words** are extracted from both the claim and the evidence — alphabetic tokens excluding 111 English stopwords.

2. **Stemming** is applied via a custom three-stage suffix-stripping stemmer (not a full Porter stemmer). Morphological variants collapse to a common stem (e.g., *hallucinated* ≡ *hallucinations*, *citations* ≡ *citation*).

3. **Coverage metric**: `coverage = |claim_stems ∩ evidence_stems| / |claim_stems|` — the fraction of the claim's content-word stems that also appear in the evidence passage.

4. **Threshold**: `MIN_CONTRADICTION_EVIDENCE_OVERLAP = 0.30` — the evidence must share at least 30% of the claim's content vocabulary.

5. **Applicability**: The gate filters **only** strong contradiction candidates. Conflict and contradiction-dominance decisions consume that filtered set. Entailments, moderate support, numeric verification and provenance checks are not independently validated by lexical coverage.

**Important limitations:**

- Lexical coverage is a **heuristic**, not a calibrated benchmark result.
- **Synonym-based contradictions** (genuine contradictions expressed with different vocabulary) may conservatively produce `ABSTAIN` if no stems overlap.
- The custom stemmer is **not** a general-purpose semantic similarity model.
- **ASCII-only tokenization**: non-ASCII terms (Greek letters, accented characters) may lose characters in the content-word extraction.
- The 0.30 threshold was chosen to satisfy Cases A–D and may need adjustment for claims of different lengths.

### Step 4: Strong Entailment → PASS or WARN

If only strong entailments (≥0.70) exist with verified provenance:

- **Numeric claim with matching numbers in evidence** → `PASS` / `SUPPORTED` / `STRONG_ENTAILMENT_WITH_PROVENANCE`
- **Numeric claim with non-matching numbers** → `WARN` / `PARTIALLY_SUPPORTED` / `NUMERIC_VALUE_NOT_VERIFIED`
- **Non-numeric claim** → `PASS` / `SUPPORTED` / `STRONG_ENTAILMENT_WITH_PROVENANCE`

### Step 5: Moderate Entailment → WARN

If no strong entailment/contradiction but moderate entailment exists (0.50–0.70, entailment > neutral, entailment > contradiction, verified provenance):

- **Numeric match present** → `WARN` / `PARTIALLY_SUPPORTED` / `MODERATE_ENTAILMENT`
- **Numeric mismatch** → `WARN` / `PARTIALLY_SUPPORTED` / `MODERATE_ENTAILMENT_NUMERIC_MISMATCH`

### Step 6: No Threshold Crossed → ABSTAIN

If no candidate crosses any threshold:

- → `ABSTAIN` / `INSUFFICIENT_EVIDENCE` / `NO_SEMANTIC_SCORE_CROSSED_THRESHOLD`

## BM25 Relevance Ordering

When multiple candidates are available at the same verdict level, the best candidate is selected by:

1. **Lower BM25 rank** (rank 0 = most relevant)
2. **Higher NLI score** (entailment for support, contradiction for contradiction)
3. **Higher BM25 score**
4. **Earlier canonical source position** (lower start_char)

This ensures that the reported evidence is the most retrieval-relevant passage, not simply the one with the highest NLI score.

## Provenance Verification

Provenance is verified at two levels:

### Chunk-level (during loading)
Every persisted chunk is verified to be an exact character span of the canonical source text. If verification fails, `VerificationIntegrityError` is raised and the source is treated as corrupted (fail-closed).

### Window-level (during evidence extraction)
Each evidence window derived from a chunk is verified as an exact span of the canonical source. Offsets are mapped to page numbers using `page_range_for_span()`.

### Match strictness

- **Exact match only**: case-sensitive, no whitespace normalization, no fuzzy matching
- **Quote search**: `verify_exact_quote()` can reject multiple occurrences as `AMBIGUOUS_MULTIPLE_OCCURRENCES` when uniqueness is required. The V2 pipeline uses exact supplied spans; repeated text alone does not invalidate those spans.
- **Page mapping**: zero-width blank pages are excluded

## NLI Engine

- **Model:** `cross-encoder/nli-deberta-v3-small`
- **Framework:** PyTorch (CPU-only, no GPU required)
- **Singleton:** Loaded once per process via `get_nli_engine()`
- **Scoring:** All evidence windows for a claim are batched into a single NLI call for efficiency
- **Non-finite scores:** Raise `VerificationIntegrityError` (fail-closed)
