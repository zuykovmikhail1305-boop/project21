"""Validation service: NLI-based fact-checking for LLM answers.

Uses a cross-encoder NLI model (e.g., cross-encoder/nli-deberta-v3-small) to
check if the LLM's answer is factually supported by the source document chunks.
"""

from typing import Optional

from sentence_transformers import CrossEncoder

from app.core import config


# Pre-configured NLI model
NLI_MODEL_NAME = "cross-encoder/nli-deberta-v3-small"
NLI_THRESHOLD_CONTRADICTION = 0.5  # If contradiction score > this, mark as unsupported
NLI_THRESHOLD_ENTAILMENT = 0.5    # If entailment score > this, mark as supported


class ValidationResult:
    """Result of a single fact-check validation."""

    def __init__(
        self,
        statement: str,
        source: str,
        label: str,
        scores: dict[str, float],
    ):
        self.statement = statement
        self.source = source
        self.label = label  # "entailment" | "contradiction" | "neutral"
        self.scores = scores
        self.is_supported = label == "entailment"

    def to_dict(self) -> dict:
        return {
            "statement": self.statement,
            "source": self.source,
            "label": self.label,
            "scores": self.scores,
            "is_supported": self.is_supported,
        }


class FactValidator:
    """NLI-based fact validator for LLM-generated answers.

    Splits the answer into sentences and checks each against the source chunks
    using a cross-encoder NLI model.
    """

    def __init__(self, model_name: str = NLI_MODEL_NAME):
        self.model: Optional[CrossEncoder] = None
        self.model_name = model_name

    def _lazy_load_model(self):
        """Load the NLI model on first use."""
        if self.model is None:
            self.model = CrossEncoder(self.model_name)

    def _split_sentences(self, text: str) -> list[str]:
        """Split text into sentences (simple Russian-aware split)."""
        import re
        # Split on sentence-ending punctuation followed by space or end-of-string
        sentences = re.split(r'(?<=[.!?])\s+', text)
        # Filter out empty strings and very short fragments
        return [s.strip() for s in sentences if len(s.strip()) > 10]

    async def validate(
        self,
        answer: str,
        sources: list[dict],
    ) -> list[ValidationResult]:
        """Validate each sentence of the answer against source chunks.

        Args:
            answer: The LLM-generated answer text.
            sources: List of source chunks with 'content' key.

        Returns:
            List of ValidationResult objects.
        """
        self._lazy_load_model()

        sentences = self._split_sentences(answer)
        if not sentences:
            return []

        # Build premise from all source chunks
        premise_parts = [s.get("content", "") for s in sources if s.get("content")]
        if not premise_parts:
            return []

        premise = " ".join(premise_parts)

        results: list[ValidationResult] = []
        for sentence in sentences:
            # NLI model expects (premise, hypothesis) pairs
            model_input = [(premise, sentence)]
            scores = self.model.predict(model_input)[0]  # [contradiction, entailment, neutral]

            label_idx = scores.argmax()
            labels = ["contradiction", "entailment", "neutral"]
            label = labels[label_idx]

            results.append(ValidationResult(
                statement=sentence,
                source=premise[:200] + "..." if len(premise) > 200 else premise,
                label=label,
                scores={
                    "contradiction": float(scores[0]),
                    "entailment": float(scores[1]),
                    "neutral": float(scores[2]),
                },
            ))

        return results

    async def validate_with_summary(
        self,
        answer: str,
        sources: list[dict],
    ) -> dict:
        """Validate and return a summary dict with overall support score.

        Returns:
            dict with:
                - results: list of per-sentence validation results
                - supported_ratio: fraction of sentences that are supported
                - has_contradictions: True if any sentence contradicts sources
                - overall: "supported" | "partial" | "contradiction"
        """
        results = await self.validate(answer, sources)

        if not results:
            return {
                "results": [],
                "supported_ratio": 0.0,
                "has_contradictions": False,
                "overall": "unknown",
            }

        n_supported = sum(1 for r in results if r.is_supported)
        n_contradictions = sum(1 for r in results if r.label == "contradiction")
        total = len(results)

        if n_contradictions > 0:
            overall = "contradiction"
        elif n_supported / total >= 0.7:
            overall = "supported"
        else:
            overall = "partial"

        return {
            "results": [r.to_dict() for r in results],
            "supported_ratio": n_supported / total,
            "has_contradictions": n_contradictions > 0,
            "overall": overall,
        }