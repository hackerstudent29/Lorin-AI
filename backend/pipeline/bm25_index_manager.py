"""
BM25IndexManager — Requirement 3 compliant keyword index.
Builds, persists, loads, and serves a BM25 keyword index over all chunk texts.
"""
import pickle, logging, time
from pathlib import Path
from rank_bm25 import BM25Okapi
from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)

BM25_PATH       = Path("bm25_index/bm25.pkl")
META_PATH       = Path("bm25_index/bm25_meta.pkl")
COLLECTION_NAME = "college_knowledgebase"


class BM25IndexManager:
    """
    Manages a rank_bm25.BM25Okapi index over all chunk texts in Qdrant.

    Persistence layout:
      bm25_index/bm25.pkl      — pickled BM25Okapi instance
      bm25_index/bm25_meta.pkl — {"point_count": int, "texts": list[str],
                                   "payloads": list[dict], "built_at": float}
      bm25_index/vocab.pkl     — dict[str, int] rebuilt alongside BM25

    Staleness detection: compare stored point_count vs qdrant.count().
    """

    def __init__(self, qdrant: QdrantClient):
        self._qdrant   = qdrant
        self._bm25     = None      # BM25Okapi | None
        self._texts    = []        # list[str]
        self._payloads = []        # list[dict]

    # ── Startup ───────────────────────────────────────────────────────────────

    def load_or_build(self) -> None:
        """
        Called once at API server startup.
        - If pkl absent or corrupted → rebuild from Qdrant.
        - If point count stale → rebuild.
        - Else → load from pkl.
        """
        try:
            live_count = self._qdrant.count(COLLECTION_NAME).count
        except Exception as e:
            logger.warning(f"[BM25] Could not get Qdrant count: {e}. Skipping BM25 build.")
            return

        if BM25_PATH.exists() and META_PATH.exists():
            try:
                with open(META_PATH, "rb") as f:
                    meta = pickle.load(f)
                stored_count = meta.get("point_count", -1)
                if stored_count == live_count:
                    with open(BM25_PATH, "rb") as f:
                        self._bm25 = pickle.load(f)
                    self._texts    = meta["texts"]
                    self._payloads = meta["payloads"]
                    logger.info(f"[BM25] Loaded from cache ({live_count} points).")
                    return
                else:
                    logger.info(
                        f"[BM25] Stale index (stored={stored_count}, live={live_count}). Rebuilding."
                    )
            except Exception as e:
                logger.warning(f"[BM25] Failed to load pkl: {e}. Rebuilding.")
        else:
            logger.info("[BM25] Index not found. Building from Qdrant.")

        self._rebuild(live_count)

    def _rebuild(self, point_count: int) -> None:
        """Scroll all Qdrant points, build BM25Okapi, persist."""
        texts, payloads = [], []
        offset = None
        while True:
            try:
                result = self._qdrant.scroll(
                    collection_name=COLLECTION_NAME,
                    limit=500,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                batch = result[0]
                next_offset = result[1]
            except Exception as e:
                logger.error(f"[BM25] Scroll failed: {e}")
                raise

            for pt in batch:
                text = pt.payload.get("text", "")
                if text:
                    texts.append(text)
                    payloads.append(pt.payload)
            if next_offset is None:
                break
            offset = next_offset

        if not texts:
            logger.warning("[BM25] No texts found in Qdrant. Skipping index build.")
            return

        tokenized = [t.lower().split() for t in texts]
        bm25 = BM25Okapi(tokenized)

        Path("bm25_index").mkdir(exist_ok=True)
        with open(BM25_PATH, "wb") as f:
            pickle.dump(bm25, f)
        meta = {
            "point_count": point_count,
            "texts":        texts,
            "payloads":     payloads,
            "built_at":     time.time(),
        }
        with open(META_PATH, "wb") as f:
            pickle.dump(meta, f)

        self._bm25     = bm25
        self._texts    = texts
        self._payloads = payloads

        # Rebuild vocab.pkl alongside (Req 7.6)
        try:
            from pipeline.spell_corrector import SpellCorrector
            SpellCorrector.build_from_texts(texts)
        except Exception as e:
            logger.error(f"[BM25] Vocab rebuild failed (non-blocking): {e}")

        logger.info(f"[BM25] Rebuilt index: {len(texts)} chunks, vocab refreshed.")

    # ── Query ─────────────────────────────────────────────────────────────────

    def query(self, query: str, top_k: int = 25) -> list:
        """
        Return up to top_k results as list of:
          {"text": str, "payload": dict, "bm25_rank": int, "bm25_score": float}

        Raises RuntimeError if index not loaded (caller must handle for graceful degradation).
        """
        if self._bm25 is None:
            raise RuntimeError("BM25 index not loaded.")
        tokenized_query = query.lower().split()
        scores = self._bm25.get_scores(tokenized_query)
        # Sort by descending score
        ranked_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        results = []
        for rank, idx in enumerate(ranked_idx):
            if scores[idx] > 0:  # non-zero BM25 score required (Req 3.6)
                results.append({
                    "text":       self._texts[idx],
                    "payload":    self._payloads[idx],
                    "bm25_rank":  rank,
                    "bm25_score": float(scores[idx]),
                })
        return results

    # ── Incremental append (Req 3.7) ─────────────────────────────────────────

    def append_and_rebuild(self, new_texts: list, new_payloads: list) -> None:
        """Called by process_dataset.py after indexing new PDFs."""
        self._texts.extend(new_texts)
        self._payloads.extend(new_payloads)
        try:
            live_count = self._qdrant.count(COLLECTION_NAME).count
        except Exception as e:
            logger.warning(f"[BM25] Could not get Qdrant count for rebuild: {e}")
            live_count = len(self._texts)
        self._rebuild(live_count)
