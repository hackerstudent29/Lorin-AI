"""
QueryRewriter — Requirement 6 compliant condense-question rewriter.
Rewrites follow-up messages into standalone questions using conversation history.
"""
import re, logging, requests
from typing import Optional

logger = logging.getLogger(__name__)

# Constants (from rag_config)
REWRITE_MIN_HISTORY_TURNS = 1    # Fire after 1 prior assistant turn
REWRITE_MAX_CONTEXT_TURNS = 6    # Include last 6 turns (user+assistant)
REWRITE_TIMEOUT_SEC = 10         # LLM call timeout

class QueryRewriter:
    """
    LLM-based condense-question rewriter for multi-turn conversations (Req 6).
    """

    def __init__(self, nvidia_api_key: str, supabase_client=None, db_conn_fn=None):
        self._api_key   = nvidia_api_key
        self._supabase  = supabase_client
        self._db_conn   = db_conn_fn

    def _get_history(self, session_id: str) -> list:
        if not self._db_conn or not session_id:
            return []
        try:
            conn = self._db_conn()
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("""
                SELECT role, content FROM chat_messages
                WHERE session_id = %s::uuid
                ORDER BY created_at DESC
                LIMIT %s
            """, (session_id, REWRITE_MAX_CONTEXT_TURNS + 2))
            rows = cur.fetchall()
            cur.close()
            conn.close()
            filtered = []
            skipped_current = False
            for role, content in rows:
                if not skipped_current and role == "user":
                    skipped_current = True
                    continue
                filtered.append({"role": role, "content": content})
                if len(filtered) >= REWRITE_MAX_CONTEXT_TURNS:
                    break
            return list(reversed(filtered))
        except Exception as e:
            logger.warning(f"[QueryRewriter] Failed to fetch history: {e}")
            return []

    def rewrite(self, user_message: str, session_id: Optional[str]) -> tuple:
        """
        Rewrite a follow-up question into a standalone question.
        Returns: (rewritten_query: str, was_rewritten: bool)
        """
        if not session_id:
            return user_message, False

        history = self._get_history(session_id)

        history_str = ""
        for msg in history:
            role_label = "User" if msg["role"] == "user" else "Assistant"
            if msg["role"] == "assistant":
                # Don't aggressively split by '.' which might cut off vital context like lists or exact names
                content = msg["content"][:400].replace('\n', ' ')
                if len(msg["content"]) > 400: content += "..."
            else:
                content = msg["content"][:300].replace('\n', ' ')
            history_str += f"{role_label}: {content}\n"

        if history_str.strip():
            prompt = (
                "You are an expert search query optimizer for a college chatbot.\n"
                "Task: Rewrite the current user question into a clear, concise, and formal standalone search question.\n"
                "Use the conversation history ONLY to resolve pronouns or missing context (e.g. 'it', 'that', 'the department', 'he', 'him').\n"
                "If the user asks about a specific person discussed recently, replace 'him' or 'her' with their full name.\n"
                f"History:\n{history_str}\n"
                f"Current question: {user_message}\n"
                "Output ONLY the optimized, clean rewritten question without quotation marks or extra text."
            )
        else:
            prompt = (
                "You are an expert search query optimizer for Mohamed Sathak A.J. College of Engineering (MSAJCE).\n"
                "Task: Convert noisy, informal, or poorly phrased user text into a clear, formal standalone search question.\n"
                f"User text: {user_message}\n"
                "Output ONLY the optimized, clean rewritten question without quotation marks or extra text."
            )

        try:
            res = requests.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":       "meta/llama-3.1-8b-instruct",
                    "messages":    [{"role": "user", "content": prompt}],
                    "temperature": 0.0,
                    "max_tokens":  120,
                },
                timeout=REWRITE_TIMEOUT_SEC,
            )
            res.raise_for_status()
            rewritten = res.json()["choices"][0]["message"]["content"].strip()
            # Strip any leading labels the model might add
            rewritten = re.sub(r"^(Standalone question:|Rewritten:|Question:)\s*", "", rewritten, flags=re.IGNORECASE).strip()

            if rewritten and rewritten.lower() != user_message.lower():
                logger.debug(f"[QueryRewriter] '{user_message}' -> '{rewritten}'")
                return rewritten, True
            return user_message, False

        except Exception as e:
            logger.warning(f"[QueryRewriter] LLM call failed (using original): {e}")
            return user_message, False
