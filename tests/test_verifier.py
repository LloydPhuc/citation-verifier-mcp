"""Tests for citation_v2.verifier module (pure logic)."""

import pytest

from citation_v2.verifier import (
    EVIDENCE_WINDOW_OVERLAP_CHARS,
    EVIDENCE_WINDOW_TARGET_CHARS,
    PARTIAL_ENTAILMENT_THRESHOLD,
    EvidenceCandidate,
    VerificationInputError,
    _best_contradiction,
    _best_entailment,
    _best_neutral,
    _decide,
    _normalize_number_token,
    _validate_claim,
    extract_numeric_tokens,
    numeric_claim_matches,
)


@pytest.mark.unit
class TestValidateClaim:
    def test_valid_claim(self):
        assert _validate_claim("  hello  ") == "hello"

    def test_non_string_raises(self):
        with pytest.raises(
            VerificationInputError, match="must be a string"
        ):
            _validate_claim(123)

    def test_empty_raises(self):
        with pytest.raises(
            VerificationInputError, match="cannot be empty"
        ):
            _validate_claim("   ")


@pytest.mark.unit
class TestExtractNumericTokens:
    def test_simple_number(self):
        assert extract_numeric_tokens("value is 42") == ("42",)

    def test_decimal_number(self):
        assert extract_numeric_tokens("ratio 0.75") == (
            "0.75",
        )

    def test_percentage(self):
        assert extract_numeric_tokens("92.4% increase") == (
            "92.4",
        )

    def test_scientific_notation(self):
        assert extract_numeric_tokens("1e10 molecules") == (
            "1e10",
        )

    def test_negative_number(self):
        assert extract_numeric_tokens("temp -5 degrees") == (
            "-5",
        )

    def test_multiple_numbers(self):
        result = extract_numeric_tokens("from 10 to 20")
        assert result == ("10", "20")

    def test_no_numbers_returns_empty(self):
        assert extract_numeric_tokens("no numbers here") == ()

    def test_non_string_raises(self):
        with pytest.raises(TypeError, match="must be a string"):
            extract_numeric_tokens(123)

    def test_comma_separator(self):
        assert extract_numeric_tokens("1,234 people") == (
            "1234",
        )

    def test_plus_prefix_removed(self):
        assert extract_numeric_tokens("value +5") == ("5",)

    def test_doi_like_does_not_match(self):
        tokens = extract_numeric_tokens(
            "10.1038/s41467-025-58551-6"
        )
        assert "10" not in tokens


@pytest.mark.unit
class TestNormalizeNumberToken:
    def test_removes_commas(self):
        assert _normalize_number_token("1,234") == "1234"

    def test_removes_percent(self):
        assert _normalize_number_token("50%") == "50"

    def test_removes_plus(self):
        assert _normalize_number_token("+42") == "42"

    def test_strips_whitespace(self):
        assert _normalize_number_token("  10  ") == "10"


@pytest.mark.unit
class TestNumericClaimMatches:
    def test_no_numbers_in_claim(self):
        assert numeric_claim_matches(
            "it was shown", "evidence shows"
        ) is True

    def test_number_present_in_evidence(self):
        assert numeric_claim_matches(
            "value is 42", "the value 42 confirms"
        ) is True

    def test_number_absent_in_evidence(self):
        assert numeric_claim_matches(
            "value is 42", "the value 99 confirms"
        ) is False

    def test_multiple_numbers_all_present(self):
        assert numeric_claim_matches(
            "from 10 to 20", "range 10 to 20 confirmed"
        ) is True

    def test_multiple_numbers_one_missing(self):
        assert numeric_claim_matches(
            "from 10 to 20", "range 10 to 30 confirmed"
        ) is False

    def test_percentage_match(self):
        assert numeric_claim_matches(
            "92.4% increase", "increase of 92.4%"
        ) is True


@pytest.mark.unit
class TestDecideEmpty:
    def test_empty_candidates_abstain(self):
        verdict, semantic, reason, selected = _decide([])
        assert verdict == "ABSTAIN"
        assert semantic == "INSUFFICIENT_EVIDENCE"
        assert reason == "NO_EVIDENCE_WINDOWS"
        assert selected is None


@pytest.mark.unit
class TestDecideConstants:
    def test_evidence_window_target_chars(self):
        assert EVIDENCE_WINDOW_TARGET_CHARS == 1600

    def test_evidence_window_overlap(self):
        assert EVIDENCE_WINDOW_OVERLAP_CHARS == 300

    def test_partial_entailment_threshold(self):
        assert PARTIAL_ENTAILMENT_THRESHOLD == 0.50


def _make_candidate(
    *,
    bm25_rank=1,
    bm25_score=0.9,
    entailment=0.8,
    contradiction=0.1,
    neutral=0.1,
    provenance_verified=True,
    numeric_match=True,
    quote="evidence",
    start_char=0,
    end_char=8,
):
    return EvidenceCandidate(
        bm25_rank=bm25_rank,
        bm25_score=bm25_score,
        chunk_id=1,
        chunk_index=0,
        quote=quote,
        start_char=start_char,
        end_char=end_char,
        page_start=1,
        page_end=1,
        contradiction=contradiction,
        entailment=entailment,
        neutral=neutral,
        predicted_label="entailment" if entailment > max(
            contradiction, neutral
        ) else "neutral",
        premise_truncated=False,
        provenance_verified=provenance_verified,
        numeric_match=numeric_match,
    )


@pytest.mark.unit
class TestDecideStrongEntailment:
    def test_strong_entailment_pass(self):
        candidate = _make_candidate(
            entailment=0.95,
            contradiction=0.02,
            neutral=0.03,
        )
        verdict, semantic, reason, selected = _decide(
            [candidate]
        )
        assert verdict == "PASS"
        assert semantic == "SUPPORTED"
        assert reason == "STRONG_ENTAILMENT_WITH_PROVENANCE"
        assert selected is not None

    def test_strong_entailment_no_numeric_warn(self):
        candidate = _make_candidate(
            entailment=0.95,
            numeric_match=False,
        )
        verdict, semantic, reason, selected = _decide(
            [candidate]
        )
        assert verdict == "WARN"
        assert semantic == "PARTIALLY_SUPPORTED"
        assert reason == "NUMERIC_VALUE_NOT_VERIFIED"

    def test_entailment_without_provenance_not_strong(self):
        candidate = _make_candidate(
            entailment=0.95,
            provenance_verified=False,
        )
        verdict, semantic, _reason, _selected = _decide(
            [candidate]
        )
        assert verdict == "ABSTAIN"


@pytest.mark.unit
class TestDecideContradiction:
    def test_strong_contradiction_fail(self):
        candidate = _make_candidate(
            contradiction=0.95,
            entailment=0.02,
            neutral=0.03,
        )
        verdict, semantic, reason, selected = _decide(
            [candidate]
        )
        assert verdict == "FAIL"
        assert semantic == "CONTRADICTED"
        assert reason == "STRONG_CONTRADICTION"

    def test_contradiction_without_provenance_not_strong(self):
        candidate = _make_candidate(
            contradiction=0.95,
            provenance_verified=False,
        )
        verdict, semantic, _reason, _selected = _decide(
            [candidate]
        )
        assert verdict == "ABSTAIN"


@pytest.mark.unit
class TestDecideConflict:
    def test_conflicting_evidence_warns(self):
        entailment = _make_candidate(
            entailment=0.95,
            bm25_rank=1,
        )
        contradiction = _make_candidate(
            contradiction=0.95,
            entailment=0.02,
            bm25_rank=2,
        )
        verdict, semantic, reason, selected = _decide(
            [entailment, contradiction]
        )
        assert verdict == "WARN"
        assert semantic == "CONFLICTING_EVIDENCE"
        assert (
            reason
            == "STRONG_ENTAILMENT_AND_CONTRADICTION"
        )


@pytest.mark.unit
class TestDecideContradictionsDominate:
    """
    Regression tests for the contradiction-dominance heuristic.

    When contradictions overwhelmingly dominate strong entailments
    (both in count and max score), the entailment signal is treated
    as spurious NLI confusion and the verdict becomes ABSTAIN.
    """

    def test_contradictions_dominate_returns_abstain(self):
        """
        One strong entailment, many strong contradictions with higher scores.

        Contradiction count (8) >= 3 * entailment count (1).
        Max contradiction (0.99) > max entailment (0.81) + 0.15 (0.96).

        Expected: ABSTAIN with CONTRADICTIONS_DOMINATE_ENTAILMENT_SIGNAL.
        """
        entailment = _make_candidate(
            entailment=0.81,
            contradiction=0.05,
            bm25_rank=1,
        )
        # 8 strong contradictions with higher scores
        contradictions = [
            _make_candidate(
                contradiction=0.99,
                entailment=0.01,
                bm25_rank=i + 2,
            )
            for i in range(8)
        ]

        verdict, semantic, reason, selected = _decide(
            [entailment] + contradictions
        )
        assert verdict == "ABSTAIN"
        assert semantic == "INSUFFICIENT_EVIDENCE"
        assert reason == "CONTRADICTIONS_DOMINATE_ENTAILMENT_SIGNAL"

    def test_insufficient_contradiction_ratio_returns_warn(self):
        """
        Two strong entailments, four strong contradictions.

        Contradiction count (4) < 3 * entailment count (2) = 6.

        Expected: WARN (genuine conflict), not ABSTAIN.
        """
        entailments = [
            _make_candidate(
                entailment=0.85,
                contradiction=0.05,
                bm25_rank=1,
            ),
            _make_candidate(
                entailment=0.80,
                contradiction=0.05,
                bm25_rank=2,
            ),
        ]
        contradictions = [
            _make_candidate(
                contradiction=0.95,
                entailment=0.02,
                bm25_rank=3 + i,
            )
            for i in range(4)
        ]

        verdict, semantic, reason, _selected = _decide(
            entailments + contradictions
        )
        assert verdict == "WARN"
        assert reason == "STRONG_ENTAILMENT_AND_CONTRADICTION"

    def test_insufficient_score_margin_returns_warn(self):
        """
        One strong entailment, three strong contradictions.
        But max contradiction (0.92) <= max entailment (0.81) + 0.15 = 0.96.

        Score margin condition not met.

        Expected: WARN (genuine conflict).
        """
        entailment = _make_candidate(
            entailment=0.81,
            contradiction=0.05,
            bm25_rank=1,
        )
        contradictions = [
            _make_candidate(
                contradiction=0.92,
                entailment=0.03,
                bm25_rank=i + 2,
            )
            for i in range(3)
        ]

        verdict, _semantic, reason, _selected = _decide(
            [entailment] + contradictions
        )
        assert verdict == "WARN"
        assert reason == "STRONG_ENTAILMENT_AND_CONTRADICTION"

    def test_no_strong_entailment_contradiction_still_fails(self):
        """
        Zero strong entailments, multiple strong contradictions.

        Should not trigger dominance branch (no entailments to dominate).
        Expected: FAIL (strong contradiction).
        """
        contradictions = [
            _make_candidate(
                contradiction=0.95,
                entailment=0.02,
                bm25_rank=i + 1,
            )
            for i in range(5)
        ]

        verdict, semantic, reason, _selected = _decide(
            contradictions
        )
        assert verdict == "FAIL"
        assert semantic == "CONTRADICTED"
        assert reason == "STRONG_CONTRADICTION"

    def test_provenance_false_prevents_dominance_check(self):
        """
        Strong entailments and contradictions, but entailment has
        provenance_verified=False.

        Dominance check only considers provenance-verified candidates.

        Expected: WARN (conflict between verified candidates).
        """
        entailment = _make_candidate(
            entailment=0.85,
            provenance_verified=False,
            bm25_rank=1,
        )
        contradictions = [
            _make_candidate(
                contradiction=0.95,
                entailment=0.02,
                bm25_rank=i + 2,
            )
            for i in range(5)
        ]

        verdict, _semantic, reason, _selected = _decide(
            [entailment] + contradictions
        )
        # Entailment not verified, so 0 strong entailments.
        # Should be FAIL (strong contradiction) or WARN depending on counts.
        # With 0 verified entailments and 5 verified contradictions:
        # 0 strong entailments -> FAIL
        assert verdict == "FAIL"
        assert reason == "STRONG_CONTRADICTION"

    def test_all_candidates_unverified_returns_abstain(self):
        """
        All candidates have provenance_verified=False.

        No strong candidates, should fall through to neutral/ABSTAIN.
        """
        candidates = [
            _make_candidate(
                entailment=0.95,
                provenance_verified=False,
                bm25_rank=1,
            ),
            _make_candidate(
                contradiction=0.95,
                provenance_verified=False,
                bm25_rank=2,
            ),
        ]

        verdict, semantic, reason, _selected = _decide(
            candidates
        )
        assert verdict == "ABSTAIN"


@pytest.mark.unit
class TestDecideModerateEntailment:
    def test_moderate_entailment_warn(self):
        candidate = _make_candidate(
            entailment=0.60,
            contradiction=0.20,
            neutral=0.20,
            numeric_match=True,
        )
        verdict, semantic, reason, selected = _decide(
            [candidate]
        )
        assert verdict == "WARN"
        assert semantic == "PARTIALLY_SUPPORTED"
        assert reason == "MODERATE_ENTAILMENT"

    def test_moderate_entailment_no_numeric(self):
        candidate = _make_candidate(
            entailment=0.60,
            contradiction=0.20,
            neutral=0.20,
            numeric_match=False,
        )
        verdict, semantic, reason, selected = _decide(
            [candidate]
        )
        assert verdict == "WARN"
        assert reason == "MODERATE_ENTAILMENT_NUMERIC_MISMATCH"

    def test_moderate_entailment_requires_higher_than_others(
        self,
    ):
        candidate = _make_candidate(
            entailment=0.60,
            neutral=0.70,
            contradiction=0.20,
            numeric_match=True,
        )
        verdict, _semantic, _reason, _selected = _decide(
            [candidate]
        )
        assert verdict == "ABSTAIN"


@pytest.mark.unit
class TestDecideNoSupport:
    def test_abstain_no_support(self):
        candidate = _make_candidate(
            entailment=0.30,
            neutral=0.50,
            contradiction=0.20,
        )
        verdict, semantic, reason, selected = _decide(
            [candidate]
        )
        assert verdict == "ABSTAIN"
        assert semantic == "INSUFFICIENT_EVIDENCE"
        assert selected is not None


@pytest.mark.unit
class TestBestSelection:
    def test_best_entailment_none(self):
        assert _best_entailment([]) is None

    def test_best_contradiction_none(self):
        assert _best_contradiction([]) is None

    def test_best_neutral_none(self):
        assert _best_neutral([]) is None

    def test_best_entailment_priority(self):
        c1 = _make_candidate(
            bm25_rank=1, entailment=0.8
        )
        c2 = _make_candidate(
            bm25_rank=2, entailment=0.9
        )
        assert _best_entailment([c1, c2]) is c1
