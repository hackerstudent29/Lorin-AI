"""
HybridRetriever — Requirement 3 compliant parallel BM25 + dense retriever.
Merges results via Reciprocal Rank Fusion, returns up to 40 candidates.
"""
import logging
import concurrent.futures
from pipeline.bm25_index_manager import BM25IndexManager
from pipeline.metadata_filter import MetadataFilter

logger = logging.getLogger(__name__)

# Constants (from rag_config)
RRF_K       = 60   # RRF constant k in score = 1/(k+rank)
TOP_K       = 10   # Per-retriever candidate count (optimized for fast low-latency transfer)
RRF_OUT     = 15   # Max merged candidates after RRF fusion


class HybridRetriever:
    """
    Parallel BM25 + dense search merged via Reciprocal Rank Fusion (Req 3).

    score(d) = sum(1 / (RRF_K + rank(d))) across all ranked lists
    """

    def __init__(self, bm25_mgr: BM25IndexManager, qdrant_client, embed_fn, collection: str):
        """
        Args:
            bm25_mgr: BM25IndexManager instance
            qdrant_client: QdrantClient instance
            embed_fn: callable(str) -> list[float]  (embedding function)
            collection: Qdrant collection name
        """
        self._bm25     = bm25_mgr
        self._qdrant   = qdrant_client
        self._embed    = embed_fn
        self._coll     = collection
        self._filter   = MetadataFilter()

    def retrieve(self, query: str, keywords: str, category: str = None, entity_id: str = None, q_vec: list = None, source_file: str = None) -> list:
        """
        Retrieve up to RRF_OUT (40) candidates via BM25 + dense fusion.

        Args:
            query:    user query (for dense embedding)
            keywords: expanded keywords string (for BM25)
            category: optional category filter for dense search
            entity_id: optional entity filter for dense search
            q_vec:    optional pre-computed embedding vector
            source_file: optional source_file to restrict both BM25 and Dense search

        Returns:
            list of dicts: {"text": str, "payload": dict, "rrf_score": float,
                            "dense_rank": int, "bm25_rank": int}
        """
        bm25_results   = []
        dense_results  = []
        filter_fallback = False

        # ── Run BM25 and dense searches in parallel ───────────────────────────
        def run_bm25():
            try:
                return self._bm25.query(keywords or query, top_k=TOP_K, category=category, entity_id=entity_id, source_file=source_file)
            except Exception as e:
                logger.warning(f"[HybridRetriever] BM25 search failed (dense-only fallback): {e}")
                return []   # Req 3.9 — graceful degradation

        def run_dense():
            try:
                vec = q_vec if q_vec is not None else self._embed(query)
                qdrant_filter = self._filter.build_filter(category, entity_id, source_file=source_file)

                hits = []
                # Try filtered search first
                if qdrant_filter:
                    try:
                        if hasattr(self._qdrant, "query_points"):
                            r = self._qdrant.query_points(
                                collection_name=self._coll,
                                query=vec,
                                query_filter=qdrant_filter,
                                limit=TOP_K,
                                with_payload=True,
                            )
                            hits = r.points
                        else:
                            hits = self._qdrant.search(
                                collection_name=self._coll,
                                query_vector=vec,
                                query_filter=qdrant_filter,
                                limit=TOP_K,
                            )
                    except Exception as filter_err:
                        # Payload index missing or filter error — fall back to unfiltered
                        logger.warning(f"[HybridRetriever] Filtered search failed ({filter_err}), falling back to unfiltered")
                        qdrant_filter = None
                        hits = []

                    # Fallback to unfiltered if too few hits (Req 2.3, 2.6)
                    if hits and self._filter.should_fallback(len(hits), category, source_file=source_file):
                        qdrant_filter = None

                # Run unfiltered if no filter or fallback triggered
                if not qdrant_filter:
                    if hasattr(self._qdrant, "query_points"):
                        r = self._qdrant.query_points(
                            collection_name=self._coll,
                            query=vec,
                            limit=TOP_K,
                            with_payload=True,
                        )
                        hits = r.points
                    else:
                        hits = self._qdrant.search(
                            collection_name=self._coll,
                            query_vector=vec,
                            limit=TOP_K,
                        )

                return [
                    {
                        "text":    h.payload.get("text", ""),
                        "payload": h.payload,
                        "score":   h.score if hasattr(h, "score") else 0.0,
                    }
                    for h in hits
                    if h.payload.get("text", "")
                ]
            except Exception as e:
                logger.warning(f"[HybridRetriever] Dense search failed: {e}")
                return []

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            fut_bm25  = ex.submit(run_bm25)
            fut_dense = ex.submit(run_dense)
            bm25_results  = fut_bm25.result()
            dense_results = fut_dense.result()

        logger.debug(
            f"[HybridRetriever] BM25={len(bm25_results)}, "
            f"dense={len(dense_results)} candidates before RRF"
        )

        # ── Dynamically Weighted Score Fusion (DBSF) ──────────────────────────
        import re
        
        # 1. Determine Dynamic Weights
        # If query contains numbers (e.g. course codes, years, phone numbers), weight BM25 higher
        has_digits = bool(re.search(r'\d', query))
        bm25_w = 0.7 if has_digits else 0.3
        dense_w = 0.3 if has_digits else 0.7

        # Use chunk_hash as dedup key, fall back to text[:64]
        def get_key(item: dict) -> str:
            payload = item.get("payload", {})
            return payload.get("chunk_hash") or item.get("text", "")[:64]

        # 2. Normalize Scores (Min-Max)
        def normalize(results):
            if not results: return {}
            max_s = max((r.get("score", 0.0) for r in results), default=1.0)
            min_s = min((r.get("score", 0.0) for r in results), default=0.0)
            range_s = max_s - min_s
            
            norm_dict = {}
            for r in results:
                key = get_key(r)
                if range_s > 0:
                    norm_dict[key] = (r.get("score", 0.0) - min_s) / range_s
                else:
                    norm_dict[key] = 1.0  # If only 1 result or all identical, it's a perfect score
            return norm_dict

        bm25_norm = normalize(bm25_results)
        dense_norm = normalize(dense_results)

        fusion_scores: dict = {}
        key_to_item: dict = {}

        for rank, item in enumerate(bm25_results):
            key = get_key(item)
            fusion_scores[key] = fusion_scores.get(key, 0.0) + (bm25_norm.get(key, 0.0) * bm25_w)
            key_to_item[key] = {"text": item["text"], "payload": item["payload"],
                                 "bm25_rank": rank, "dense_rank": -1}

        for rank, item in enumerate(dense_results):
            key = get_key(item)
            fusion_scores[key] = fusion_scores.get(key, 0.0) + (dense_norm.get(key, 0.0) * dense_w)
            if key in key_to_item:
                key_to_item[key]["dense_rank"] = rank
            else:
                key_to_item[key] = {"text": item["text"], "payload": item["payload"],
                                     "bm25_rank": -1, "dense_rank": rank}

        # Sort by Fusion score descending, return top RRF_OUT
        sorted_keys = sorted(fusion_scores.keys(), key=lambda k: fusion_scores[k], reverse=True)[:RRF_OUT]

        merged = []
        for key in sorted_keys:
            entry = key_to_item[key]
            merged.append({
                "text":        entry["text"],
                "payload":     entry["payload"],
                "fusion_score": fusion_scores[key],
                "dense_rank":  entry["dense_rank"],
                "bm25_rank":   entry["bm25_rank"],
            })

        logger.debug(f"[HybridRetriever] DBSF merged={len(merged)} candidates (max {RRF_OUT}) | Weights: BM25={bm25_w}, Dense={dense_w}")
        return merged
