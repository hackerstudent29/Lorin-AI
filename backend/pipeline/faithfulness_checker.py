"""
FaithfulnessChecker — Requirement 8 compliant conditional grounding verifier.
Only invoked when reranker confidence is low (max logit < FAITHFULNESS_TRIGGER_THRESHOLD).
"""
import logging, requests

logger = logging.getLogger(__name__)

# NVIDIA reranker returns raw logits in range ~-20 to +5.
# -18.0 means genuinely low confidence in this scale.
FAITHFULNESS_TRIGGER_THRESHOLD = -18.0
FAITHFULNESS_TIMEOUT_SEC        = 10

FALLBACK_MESSAGE = (
    "That's a great question! I don't have the specific details on that right now, but our team will be happy to help. "
    "Please reach out to the MSAJCE office at 📞 +91 99400 04500 or ✉️ msajce.office@gmail.com and they'll get back to you!"
)


class FaithfulnessChecker:
    """
    Conditional faithfulness checker (Req 8).
    Returns (should_replace: bool, was_invoked: bool, passed: bool | None)
    """

    def __init__(self, nvidia_api_key: str):
        self._api_key = nvidia_api_key

    def check(self, answer: str, context: str, max_rerank_logit: float) -> tuple:
        """
        Check if answer is grounded in context (conditionally).

        High confidence (logit >= threshold): (False, False, None)
        Low confidence + grounded:            (False, True,  True)
        Low confidence + NOT grounded:        (True,  True,  False)
        Low confidence + LLM error:           (False, True,  None)
        """
        if max_rerank_logit >= FAITHFULNESS_TRIGGER_THRESHOLD:
            return False, False, None

        logger.debug(
            f"[FaithfulnessChecker] Invoked (max_logit={max_rerank_logit:.3f} "
            f"< threshold={FAITHFULNESS_TRIGGER_THRESHOLD})"
        )

        prompt = (
            "You are a factual grounding checker.\n\n"
            f"Context (source documents):\n{context[:3000]}\n\n"
            f"Answer to check:\n{answer}\n\n"
            "Is every factual claim in the Answer directly supported by the Context? "
            "Answer ONLY with a single word: 'yes' or 'no'."
        )

        gateway_url = "http://localhost:3001"
        try:
            try:
                res = requests.post(
                    f"{gateway_url}/v1/chat/completions",
                    headers={"Content-Type": "application/json"},
                    json={
                        "model":       "deepseek/deepseek-v4-0709",
                        "messages":    [{"role": "user", "content": prompt}],
                        "temperature": 0.0,
                        "max_tokens":  5,
                    },
                    timeout=FAITHFULNESS_TIMEOUT_SEC,
                )
                res.raise_for_status()
            except Exception:
                # Fallback to NVIDIA NIM
                res = requests.post(
                    "https://integrate.api.nvidia.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                    json={
                        "model":       "meta/llama-3.1-8b-instruct",
                        "messages":    [{"role": "user", "content": prompt}],
                        "temperature": 0.0,
                        "max_tokens":  5,
                    },
                    timeout=FAITHFULNESS_TIMEOUT_SEC,
                )
                res.raise_for_status()

            verdict = res.json()["choices"][0]["message"]["content"].strip().lower()

            if "no" in verdict:
                logger.warning(
                    f"[FaithfulnessChecker] Answer NOT grounded (verdict='{verdict}'). "
                    "Replacing with fallback."
                )
                return True, True, False
            else:
                logger.debug(f"[FaithfulnessChecker] Answer grounded (verdict='{verdict}').")
                return False, True, True

        except Exception as e:
            logger.warning(f"[FaithfulnessChecker] LLM call failed (returning original): {e}")
            return False, True, None  # was_invoked=True, passed=None per Req 8.7

    @property
    def fallback_message(self) -> str:
        return FALLBACK_MESSAGE
