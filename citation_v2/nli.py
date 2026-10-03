from __future__ import annotations

import math
import threading
from dataclasses import asdict, dataclass
from typing import Any, Sequence

import torch
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
)

from .config import NLI_MODEL_ID


# ============================================================
# Exceptions
# ============================================================

class NLIError(RuntimeError):
    """Base NLI error."""


class NLIModelError(NLIError):
    """NLI model/tokenizer could not be loaded or validated."""


class NLIInputError(NLIError):
    """Claim/evidence input is invalid."""


class NLIInputTooLongError(NLIInputError):
    """
    Claim itself is too long to preserve during NLI inference.

    Evidence is allowed to be truncated.
    The claim is not silently truncated.
    """


# ============================================================
# Result schema
# ============================================================

@dataclass(frozen=True)
class NLIResult:
    contradiction: float
    entailment: float
    neutral: float

    predicted_label: str

    premise_truncated: bool

    model_id: str

    @property
    def confidence(self) -> float:
        return max(
            self.contradiction,
            self.entailment,
            self.neutral,
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["confidence"] = self.confidence
        return result


# ============================================================
# Label handling
# ============================================================

_REQUIRED_LABELS = {
    "contradiction",
    "entailment",
    "neutral",
}


def _normalize_label(
    label: str,
) -> str:
    return (
        str(label)
        .strip()
        .casefold()
        .replace("-", "_")
        .replace(" ", "_")
    )


def _resolve_label_indices(
    id2label: dict[Any, Any],
) -> dict[str, int]:
    """
    Resolve model output indices for:

        contradiction
        entailment
        neutral

    We deliberately fail closed if semantic labels cannot be
    determined reliably.
    """

    resolved: dict[str, int] = {}

    for raw_index, raw_label in id2label.items():

        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue

        normalized = _normalize_label(
            str(raw_label)
        )

        if "contradiction" in normalized:
            semantic = "contradiction"

        elif "entailment" in normalized:
            semantic = "entailment"

        elif "neutral" in normalized:
            semantic = "neutral"

        else:
            continue

        if semantic in resolved:
            raise NLIModelError(
                "Duplicate semantic NLI label "
                f"detected: {semantic}"
            )

        resolved[semantic] = index

    missing = (
        _REQUIRED_LABELS
        - set(resolved)
    )

    if missing:
        raise NLIModelError(
            "Unable to resolve required NLI labels. "
            f"Missing: {sorted(missing)}. "
            f"id2label={id2label!r}"
        )

    if len(
        set(resolved.values())
    ) != 3:
        raise NLIModelError(
            "NLI semantic labels do not map "
            "to three distinct output indices."
        )

    return resolved


# ============================================================
# Input validation
# ============================================================

def _validate_text(
    value: str,
    *,
    name: str,
) -> str:

    if not isinstance(value, str):
        raise NLIInputError(
            f"{name} must be a string."
        )

    value = value.strip()

    if not value:
        raise NLIInputError(
            f"{name} cannot be empty."
        )

    return value


# ============================================================
# NLI engine
# ============================================================

class NLIEngine:
    """
    Local DeBERTa NLI inference engine.

    Critical orientation:

        premise    = source evidence
        hypothesis = claim

    Do not reverse these inputs.
    """

    def __init__(
        self,
        *,
        model_id: str = NLI_MODEL_ID,
        device: str = "cpu",
    ) -> None:

        model_id = model_id.strip()

        if not model_id:
            raise ValueError(
                "model_id cannot be empty."
            )

        if device != "cpu":
            raise ValueError(
                "Current Citation MCP NLI implementation "
                "supports CPU only."
            )

        self.model_id = model_id
        self.device = torch.device(
            device
        )

        try:
            self.tokenizer = (
                AutoTokenizer.from_pretrained(
                    model_id,
                    local_files_only=True,
                )
            )

            self.model = (
                AutoModelForSequenceClassification
                .from_pretrained(
                    model_id,
                    local_files_only=True,
                )
            )

        except Exception as exc:
            raise NLIModelError(
                f"Unable to load NLI model: "
                f"{model_id}"
            ) from exc

        self.model.to(
            self.device
        )

        self.model.eval()

        raw_id2label = dict(
            self.model.config.id2label
            or {}
        )

        self.label_indices = (
            _resolve_label_indices(
                raw_id2label
            )
        )

        self.max_length = (
            self._resolve_max_length()
        )

        self._validate_model_shape()


    def _resolve_max_length(
        self,
    ) -> int:
        """
        Determine a safe sequence limit.

        Some tokenizers expose an enormous sentinel value when no
        meaningful limit is configured, so cap at model positional
        capacity and 512.
        """

        candidates: list[int] = []

        tokenizer_limit = getattr(
            self.tokenizer,
            "model_max_length",
            None,
        )

        if isinstance(
            tokenizer_limit,
            int,
        ):
            if (
                tokenizer_limit > 0
                and tokenizer_limit < 100_000
            ):
                candidates.append(
                    tokenizer_limit
                )

        config_limit = getattr(
            self.model.config,
            "max_position_embeddings",
            None,
        )

        if isinstance(
            config_limit,
            int,
        ):
            if config_limit > 0:
                candidates.append(
                    config_limit
                )

        candidates.append(512)

        return min(candidates)


    def _validate_model_shape(
        self,
    ) -> None:

        num_labels = int(
            getattr(
                self.model.config,
                "num_labels",
                0,
            )
        )

        highest_index = max(
            self.label_indices.values()
        )

        if num_labels <= highest_index:
            raise NLIModelError(
                "NLI label mapping exceeds "
                "model output dimensionality."
            )


    def _token_count(
        self,
        text: str,
    ) -> int:
        encoded = self.tokenizer(
            text,
            add_special_tokens=False,
            truncation=False,
            return_attention_mask=False,
            return_token_type_ids=False,
            verbose=False,
        )

        input_ids = encoded.get(
            "input_ids"
        )

        if not isinstance(
            input_ids,
            list,
        ):
            raise NLIModelError(
                "Tokenizer returned an unexpected "
                "token structure."
            )

        return len(input_ids)


    def _tokenize_pair(
        self,
        *,
        evidence: str,
        claim: str,
    ) -> tuple[dict[str, torch.Tensor], bool]:
        """
        Preserve the hypothesis/claim.

        If truncation is necessary, truncate only the premise
        (source evidence).

        Length is measured without constructing an oversized
        untruncated pair, avoiding Transformers max-length warnings.
        """

        claim_tokens = self._token_count(
            claim
        )

        evidence_tokens = self._token_count(
            evidence
        )

        special_tokens = (
            self.tokenizer
            .num_special_tokens_to_add(
                pair=True
            )
        )

        # The claim + pair formatting must leave at least one
        # token of capacity for source evidence.
        if (
            claim_tokens
            + special_tokens
            >= self.max_length
        ):
            raise NLIInputTooLongError(
                "Claim is too long for the NLI model "
                "without truncation."
            )

        total_length = (
            evidence_tokens
            + claim_tokens
            + special_tokens
        )

        premise_truncated = (
            total_length
            > self.max_length
        )

        try:
            encoded = self.tokenizer(
                evidence,
                claim,
                return_tensors="pt",
                truncation="only_first",
                max_length=self.max_length,
                padding=False,
            )

        except Exception as exc:
            raise NLIInputError(
                "Unable to tokenize evidence/claim pair."
            ) from exc

        if (
            "input_ids"
            not in encoded
        ):
            raise NLIModelError(
                "Tokenizer returned no input_ids."
            )

        final_length = int(
            encoded["input_ids"].shape[-1]
        )

        if final_length > self.max_length:
            raise NLIModelError(
                "Tokenizer exceeded configured "
                "maximum sequence length."
            )

        tensors: dict[
            str,
            torch.Tensor,
        ] = {}

        for key, value in encoded.items():

            if isinstance(
                value,
                torch.Tensor,
            ):
                tensors[key] = value.to(
                    self.device
                )

        return (
            tensors,
            premise_truncated,
        )


    def _scores_from_logits(
        self,
        logits: torch.Tensor,
    ) -> tuple[
        float,
        float,
        float,
        str,
    ]:

        if logits.ndim != 1:
            raise NLIModelError(
                "Expected one-dimensional "
                "NLI logits."
            )

        if not torch.isfinite(
            logits
        ).all():
            raise NLIModelError(
                "NLI model returned NaN or "
                "infinite logits."
            )

        probabilities = torch.softmax(
            logits,
            dim=-1,
        )

        if not torch.isfinite(
            probabilities
        ).all():
            raise NLIModelError(
                "NLI model returned invalid "
                "probabilities."
            )

        contradiction = float(
            probabilities[
                self.label_indices[
                    "contradiction"
                ]
            ].item()
        )

        entailment = float(
            probabilities[
                self.label_indices[
                    "entailment"
                ]
            ].item()
        )

        neutral = float(
            probabilities[
                self.label_indices[
                    "neutral"
                ]
            ].item()
        )

        scores = {
            "contradiction":
                contradiction,
            "entailment":
                entailment,
            "neutral":
                neutral,
        }

        for name, value in scores.items():

            if (
                not math.isfinite(value)
                or value < 0.0
                or value > 1.0
            ):
                raise NLIModelError(
                    f"Invalid probability for "
                    f"{name}: {value}"
                )

        total = sum(
            scores.values()
        )

        if not math.isclose(
            total,
            1.0,
            rel_tol=1e-5,
            abs_tol=1e-5,
        ):
            raise NLIModelError(
                "NLI probabilities do not "
                f"sum to 1: {total}"
            )

        predicted_label = max(
            scores,
            key=scores.get,
        )

        return (
            contradiction,
            entailment,
            neutral,
            predicted_label,
        )


    def score(
        self,
        *,
        evidence: str,
        claim: str,
    ) -> NLIResult:
        """
        Score one source-evidence / claim pair.
        """

        evidence = _validate_text(
            evidence,
            name="evidence",
        )

        claim = _validate_text(
            claim,
            name="claim",
        )

        (
            encoded,
            premise_truncated,
        ) = self._tokenize_pair(
            evidence=evidence,
            claim=claim,
        )

        try:
            with torch.inference_mode():

                output = self.model(
                    **encoded
                )

        except Exception as exc:
            raise NLIError(
                "NLI inference failed."
            ) from exc

        logits = output.logits

        if (
            logits.ndim != 2
            or logits.shape[0] != 1
        ):
            raise NLIModelError(
                "Unexpected NLI output shape: "
                f"{tuple(logits.shape)}"
            )

        (
            contradiction,
            entailment,
            neutral,
            predicted_label,
        ) = self._scores_from_logits(
            logits[0]
        )

        return NLIResult(
            contradiction=contradiction,
            entailment=entailment,
            neutral=neutral,
            predicted_label=
                predicted_label,
            premise_truncated=
                premise_truncated,
            model_id=self.model_id,
        )


    def score_many(
        self,
        *,
        claim: str,
        evidences: Sequence[str],
    ) -> list[NLIResult]:
        """
        Score multiple candidate evidence passages.

        Current implementation evaluates candidates sequentially.
        This deliberately prioritizes correctness and predictable
        memory usage. True tensor batching can be added later.
        """

        claim = _validate_text(
            claim,
            name="claim",
        )

        results: list[
            NLIResult
        ] = []

        for index, evidence in enumerate(
            evidences
        ):

            try:
                result = self.score(
                    evidence=evidence,
                    claim=claim,
                )

            except NLIInputError as exc:
                raise NLIInputError(
                    f"Invalid evidence at index "
                    f"{index}: {exc}"
                ) from exc

            results.append(
                result
            )

        return results


# ============================================================
# Lazy process-wide singleton
# ============================================================

_ENGINE: NLIEngine | None = None

_ENGINE_LOCK = threading.Lock()


def get_nli_engine() -> NLIEngine:
    """
    Return the process-wide NLI engine.

    The ~568 MB model is loaded only once per MCP process.
    """

    global _ENGINE

    if _ENGINE is not None:
        return _ENGINE

    with _ENGINE_LOCK:

        if _ENGINE is None:
            _ENGINE = NLIEngine()

    return _ENGINE


# ============================================================
# Convenience APIs
# ============================================================

def score_nli(
    *,
    evidence: str,
    claim: str,
) -> NLIResult:

    return get_nli_engine().score(
        evidence=evidence,
        claim=claim,
    )


def score_nli_candidates(
    *,
    claim: str,
    evidences: Sequence[str],
) -> list[NLIResult]:

    return get_nli_engine().score_many(
        claim=claim,
        evidences=evidences,
    )
