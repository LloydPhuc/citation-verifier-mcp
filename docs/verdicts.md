# Verdicts Guide

## Verdict Summary

| Verdict | Semantic Class | Confidence Gate | When It's Returned |
|---|---|---|---|
| `PASS` | `SUPPORTED` | High entailment + provenance | Strong NLI entailment (≥0.70) with verified provenance and numeric match |
| `WARN` | `CONFLICTING_EVIDENCE` | Mixed signals | Both strong entailment and contradiction present |
| `WARN` | `MODERATE_ENTAILMENT` | Moderate entailment | NLI entailment 0.50–0.70 (or numeric mismatch on strong entailment) |
| `WARN` | `PARTIALLY_SUPPORTED` | Low confidence | Some relevant evidence but below thresholds |
| `FAIL` | `CONTRADICTED` | High contradiction + provenance | Strong NLI contradiction (≥0.70) with verified provenance |
| `ABSTAIN` | `INSUFFICIENT_EVIDENCE` | No strong signal | No evidence windows, no lexical candidates, or NLI below all thresholds |
| `ABSTAIN` | `UNSUPPORTED_SOURCE` | Infrastructure | Source type not supported |
| `ABSTAIN` | `SOURCE_UNAVAILABLE` | Infrastructure | Network errors, timeouts, download failures |

## Critical Rules

1. **`PASS` is forbidden without `provenance_verified == true`.** The batch processor enforces this as a final boundary check. Any ungrounded `PASS` is downgraded to `ABSTAIN` with reason `PASS_BLOCKED_BY_PROVENANCE_GATE`.

2. **Numeric claims must match exactly.** If the claim contains explicit numbers (detected via regex), every number must also appear in the evidence quote. Semantic NLI alone cannot verify numbers. A strong entailment with numeric mismatch → `WARN` with reason `NUMERIC_VALUE_NOT_VERIFIED`.

3. **Infrastructure failures → `ABSTAIN`, never `FAIL`.** A network timeout, unsupported source, or extraction error does not constitute evidence that the claim is false. It is always reported as `ABSTAIN`.

4. **Scores are separated from verdicts.** NLI scores (entailment, contradiction, neutral) are reported alongside the verdict but do not independently determine it. The decision policy applies explicit thresholds.

5. **Retrieval relevance is primary.** BM25 rank is the first ordering signal when selecting the best evidence candidate. NLI is the semantic gate, not the relevance signal.

## Decision Policy (Ordered)

The `_decide()` function in `verifier.py` applies these steps in order. The first matching step determines the verdict.

### Step 1: No Candidates → ABSTAIN

```
No evidence windows produced
  → ABSTAIN / INSUFFICIENT_EVIDENCE / NO_EVIDENCE_WINDOWS
```

### Step 2: Conflicting Strong Evidence → WARN

If **both** strong entailments (≥0.70) and strong contradictions (≥0.70) exist with verified provenance:

- **Contradictions dominate** (≥3× more contradictions than entailments, and max contradiction exceeds max entailment + 0.15):
  - → `ABSTAIN` / `INSUFFICIENT_EVIDENCE` / `CONTRADICTIONS_DOMINATE_ENTAILMENT_SIGNAL`
  - Rationale: the "entailment" signal is likely spurious NLI confusion on an unrelated claim.

- **Otherwise**:
  - → `WARN` / `CONFLICTING_EVIDENCE` / `STRONG_ENTAILMENT_AND_CONTRADICTION`

### Step 3: Strong Contradiction Only → FAIL

If only strong contradictions (≥0.70) exist with verified provenance:
- → `FAIL` / `CONTRADICTED` / `STRONG_CONTRADICTION`

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
- **Uniqueness**: quotes occurring multiple times are flagged as `AMBIGUOUS_MULTIPLE_OCCURRENCES`
- **Page mapping**: zero-width blank pages are excluded

## NLI Engine

- **Model:** `cross-encoder/nli-deberta-v3-small`
- **Framework:** PyTorch (CPU-only, no GPU required)
- **Singleton:** Loaded once per process via `get_nli_engine()`
- **Scoring:** All evidence windows for a claim are batched into a single NLI call for efficiency
- **Non-finite scores:** Raise `VerificationIntegrityError` (fail-closed)
