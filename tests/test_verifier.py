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
    _content_words,
    _decide,
    _evidence_relevant_to_claim,
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
    claim_relevant=True,
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
        claim_relevant=claim_relevant,
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


@pytest.mark.unit
class TestContentWords:
    def test_content_words_extracts_non_stopwords(self):
        words = _content_words("The paper proves elephants on Mars")
        assert "paper" in words
        assert "prove" in words
        assert "elephant" in words
        assert "mar" in words
        assert "the" not in words

    def test_content_words_stems_morphological_variants(self):
        assert _content_words("hallucinated") == _content_words("hallucinations")
        assert _content_words("citations") == _content_words("citation")
        assert _content_words("references") == _content_words("reference")
        assert _content_words("papers") == _content_words("paper")

    def test_content_words_filters_stopwords(self):
        words = _content_words("The of and or but")
        assert len(words) == 0

    def test_content_words_empty_string(self):
        assert len(_content_words("")) == 0

    def test_content_words_case_insensitive(self):
        words = _content_words("Paper PAPER paper")
        assert "paper" in words
        assert len(words) == 1

    def test_content_words_no_alphabetic(self):
        assert len(_content_words("123 456 789")) == 0


@pytest.mark.unit
class TestEvidenceRelevanceGate:
    def test_relevant_evidence_true(self):
        assert _evidence_relevant_to_claim(
            "paper studies hallucinated citations",
            "This paper discusses hallucinated and suspicious references."
        ) is True

    def test_irrelevant_evidence_false(self):
        assert _evidence_relevant_to_claim(
            "The paper proves that elephants live permanently on Mars",
            "Data sources include PubMed Central and arXiv."
        ) is False

    def test_shared_generic_keyword_not_sufficient(self):
        """
        Claim mentions 'paper' as a generic metadiscursive word.
        Evidence also mentions 'paper' but in a different context.
        Single-word overlap should be filtered out.
        """
        assert _evidence_relevant_to_claim(
            "The paper proves elephants live on Mars",
            "In this position paper, we review citation tools."
        ) is False

    def test_multiple_shared_keywords_makes_relevant(self):
        assert _evidence_relevant_to_claim(
            "the claim mentions data sources",
            "Data sources include PubMed and citation databases."
        ) is True

    def test_no_content_words_in_claim_returns_true(self):
        assert _evidence_relevant_to_claim(
            "the of and",
            "anything here"
        ) is True

    def test_empty_evidence_returns_false(self):
        assert _evidence_relevant_to_claim(
            "paper proves elephants live",
            ""
        ) is False


@pytest.mark.unit
class TestCaseCRellevanceGating:
    """
    Regression: Case C — absurd claim about elephants on Mars.

    NLI model assigns contradiction >= 0.99 to evidence passages
    that are simply *irrelevant* to the claim (about citation
    verification methodology).  These should be filtered out by
    the relevance gate, preventing a misleading FAIL.
    """

    def test_absurd_claim_irrelevant_evidence_abstain(self):
        """
        One strong contradiction from irrelevant evidence (claim_relevant=False)
        and no strong entailments.

        Expected: ABSTAIN (not FAIL), because the contradiction is
        filtered out by relevance gating.
        """
        candidate = _make_candidate(
            entailment=0.00002,
            contradiction=0.9994,
            neutral=0.0006,
            claim_relevant=False,
            bm25_rank=1,
            quote="Data sources include PubMed Central and arXiv. "
            "Disciplinary coverage: biomedical and medical literature.",
        )
        verdict, semantic, reason, selected = _decide([candidate])
        assert verdict == "ABSTAIN"
        assert semantic == "INSUFFICIENT_EVIDENCE"

    def test_absurd_claim_relevant_contradiction_still_fails(self):
        """
        A genuine, relevant contradiction should still trigger FAIL,
        even for an absurd claim.
        """
        candidate = _make_candidate(
            entailment=0.0001,
            contradiction=0.9994,
            neutral=0.0005,
            claim_relevant=True,
            bm25_rank=1,
            quote="The paper explicitly states that elephants only live on Earth.",
        )
        verdict, semantic, reason, selected = _decide([candidate])
        assert verdict == "FAIL"
        assert semantic == "CONTRADICTED"
        assert reason == "STRONG_CONTRADICTION"

    def test_absurd_claim_mixed_relevant_irrelevant_contradictions(self):
        """
        Multiple strong contradictions: some relevant (claim_relevant=True),
        some irrelevant (claim_relevant=False).

        Only relevant contradictions should count. If at least one
        relevant contradiction exists, FAIL is justified.
        """
        relevant_contra = _make_candidate(
            entailment=0.0001,
            contradiction=0.99,
            neutral=0.009,
            claim_relevant=True,
            bm25_rank=1,
            quote="The paper finds no evidence of extraterrestrial elephants.",
        )
        irrelevant_contra = _make_candidate(
            entailment=0.0001,
            contradiction=0.99,
            neutral=0.009,
            claim_relevant=False,
            bm25_rank=2,
            quote="Data sources include PubMed and arXiv.",
        )
        verdict, semantic, reason, selected = _decide(
            [relevant_contra, irrelevant_contra]
        )
        assert verdict == "FAIL"
        assert semantic == "CONTRADICTED"


@pytest.mark.unit
class TestCaseARelevanceGating:
    """
    Regression: Case A — claim "The paper studies hallucinated and
    suspicious citations."

    BM25 rank-1 evidence strongly supports the claim (entailment=0.985).
    But some windows from the same or nearby chunks produce NLI
    contradiction scores >= 0.70 on *irrelevant* text (data sources,
    bibliographic references).  These artifact contradictions should
    be filtered by relevance gating, allowing PASS instead of WARN.
    """

    def test_supported_claim_artifact_contradiction_passes(self):
        """
        Strong entailment from relevant evidence + artifact contradiction
        from irrelevant evidence.

        Expected: PASS (artifact contradiction filtered out).
        """
        entailment = _make_candidate(
            entailment=0.985,
            contradiction=0.0005,
            neutral=0.0143,
            claim_relevant=True,
            bm25_rank=1,
            quote="This paper discusses hallucinated and suspicious references.",
        )
        artifact_contra = _make_candidate(
            entailment=0.0016,
            contradiction=0.9814,
            neutral=0.0171,
            claim_relevant=False,
            bm25_rank=1,
            quote="Data sources include PubMed Central and arXiv.",
        )
        verdict, semantic, reason, selected = _decide(
            [entailment, artifact_contra]
        )
        assert verdict == "PASS"
        assert semantic == "SUPPORTED"
        assert reason == "STRONG_ENTAILMENT_WITH_PROVENANCE"

    def test_supported_claim_genuine_contradiction_warns(self):
        """
        Strong entailment from relevant evidence + genuine contradiction
        from relevant evidence that actually addresses the topic.

        Expected: WARN (CONFLICTING_EVIDENCE) — genuine conflict preserved.
        """
        entailment = _make_candidate(
            entailment=0.985,
            contradiction=0.0005,
            neutral=0.0143,
            claim_relevant=True,
            bm25_rank=1,
            quote="This paper discusses hallucinated references.",
        )
        genuine_contra = _make_candidate(
            entailment=0.001,
            contradiction=0.98,
            neutral=0.019,
            claim_relevant=True,
            bm25_rank=2,
            quote="The paper denies studying hallucinated citations.",
        )
        verdict, semantic, reason, selected = _decide(
            [entailment, genuine_contra]
        )
        assert verdict == "WARN"
        assert semantic == "CONFLICTING_EVIDENCE"

    def test_supported_claim_only_artifact_contradictions_passes(self):
        """
        Multiple strong entailments (relevant) + multiple strong
        contradictions (all irrelevant artifacts).

        Expected: PASS (all artifact contradictions filtered out).
        """
        entailments = [
            _make_candidate(
                entailment=0.985,
                contradiction=0.0005,
                claim_relevant=True,
                bm25_rank=1,
                quote="This paper studies hallucinated and suspicious citations.",
            ),
            _make_candidate(
                entailment=0.970,
                contradiction=0.01,
                claim_relevant=True,
                bm25_rank=2,
                quote="Hallucinated references are a growing challenge.",
            ),
        ]
        artifacts = [
            _make_candidate(
                entailment=0.01,
                contradiction=0.98,
                claim_relevant=False,
                bm25_rank=3,
                quote="Data sources include PubMed Central, arXiv, and bioRxiv.",
            ),
            _make_candidate(
                entailment=0.001,
                contradiction=0.99,
                claim_relevant=False,
                bm25_rank=4,
                quote="The Lancet, 407(10541), 1779-1781.",
            ),
        ]
        verdict, semantic, reason, selected = _decide(
            entailments + artifacts
        )
        assert verdict == "PASS"
        assert semantic == "SUPPORTED"


@pytest.mark.unit
class TestExistingContradictionBehaviorPreserved:
    """
    Ensure the relevance gate does not break existing contradiction
    behavior when claim_relevant=True (the default).
    """

    def test_strong_contradiction_still_fails(self):
        candidate = _make_candidate(
            contradiction=0.95,
            entailment=0.02,
            neutral=0.03,
            claim_relevant=True,
        )
        verdict, semantic, reason, selected = _decide([candidate])
        assert verdict == "FAIL"
        assert semantic == "CONTRADICTED"

    def test_conflicting_evidence_still_warns(self):
        entailment_cand = _make_candidate(
            entailment=0.95,
            bm25_rank=1,
            claim_relevant=True,
        )
        contradiction_cand = _make_candidate(
            contradiction=0.95,
            entailment=0.02,
            bm25_rank=2,
            claim_relevant=True,
        )
        verdict, semantic, reason, selected = _decide(
            [entailment_cand, contradiction_cand]
        )
        assert verdict == "WARN"
        assert semantic == "CONFLICTING_EVIDENCE"


@pytest.mark.unit
class TestStemmedRelevanceGating:
    """
    Regression: morphological variants (stemmed) must be recognized
    as topically relevant so legitimate contradictions are not filtered.
    """

    def test_stemmed_variant_relevance(self):
        """
        Claim uses 'hallucinated' and 'citations'; evidence uses
        'hallucinations' and 'citation'.  Stemming should normalize
        these to the same stem, yielding relevance above threshold.
        """
        assert _evidence_relevant_to_claim(
            "The paper studies hallucinated citations",
            "Checkifexist: Detecting citation hallucinations in the era "
            "of AI-generated content. Bibliographic accuracy of references.",
        ) is True

    def test_stemmed_variant_still_filters_irrelevant(self):
        """
        Even with stemming, a single coincidental keyword should not
        make unrelated evidence relevant.
        """
        assert _evidence_relevant_to_claim(
            "The paper proves elephants live on Mars",
            "In this position paper, we review citation tools.",
        ) is False

    def test_coverage_ratio_with_stemmed_overlap(self):
        """
        Coverage ratio should count stemmed matches toward the total.
        Claim: hallucinated citations → stems: hallucinat, citat
        Evidence: citation hallucinations → stems: citat, hallucinat
        2/2 = 1.0
        """
        from citation_v2.verifier import _claim_evidence_overlap_ratio

        ratio = _claim_evidence_overlap_ratio(
            "hallucinated citations",
            "Detecting citation hallucinations in AI-generated content.",
        )
        assert ratio >= 0.30


@pytest.mark.unit
class TestCaseBRelvanceGating:
    """
    Regression: Case B — legitimate contradiction with morphological
    word-form variants (hallucinated/hallucinations, citations/citation).

    The claim "The paper contains no references to hallucinated citations
    at all" is genuinely contradicted by evidence mentioning
    "hallucinations" and "references".  After stemming-based relevance
    gating, the contradiction should be recognized as relevant and FAIL.
    """

    def test_case_b_legitimate_contradiction_not_filtered(self):
        """
        A real contradiction from topically relevant evidence (even when
        word forms differ) should produce FAIL, not be filtered to ABSTAIN.
        """
        candidate = _make_candidate(
            entailment=0.00005,
            contradiction=0.995,
            neutral=0.004,
            claim_relevant=True,  # stemmed overlap is >= 0.30
            bm25_rank=1,
            quote="Checkifexist: Detecting citation hallucinations in "
                  "the era of AI-generated content. Bibliographic "
                  "accuracy of references.",
        )
        verdict, semantic, reason, selected = _decide([candidate])
        assert verdict == "FAIL"
        assert semantic == "CONTRADICTED"
        assert reason == "STRONG_CONTRADICTION"
