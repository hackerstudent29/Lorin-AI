"""
MetadataFilter — Requirement 2 compliant Qdrant payload filter builder.
Restricts vector search to chunks matching a specific category.
"""
import logging
from qdrant_client.models import Filter, FieldCondition, MatchValue

logger = logging.getLogger(__name__)

# Minimum filtered hits before falling back to unfiltered search
MIN_CATEGORY_HITS = 5


class MetadataFilter:
    """
    Builds Qdrant payload filters for category-based retrieval (Req 2).
    Falls back to unfiltered search when too few category hits exist.
    """

    def build_filter(self, category: str | None):
        """
        Build a Qdrant Filter for the given category, or return None.

        Args:
            category: exact category string to filter on, or None for no filter

        Returns:
            qdrant_client.models.Filter if category provided, else None
        """
        if not category:
            return None

        # Validate category against known list
        try:
            from rag_config import CATEGORY_LIST
            if category not in CATEGORY_LIST:
                logger.warning(
                    f"[MetadataFilter] Unknown category '{category}', skipping filter"
                )
                return None
        except ImportError:
            pass  # rag_config not available — allow any category

        return Filter(
            must=[
                FieldCondition(
                    key="category",
                    match=MatchValue(value=category),
                )
            ]
        )

    def should_fallback(self, hit_count: int, category: str) -> bool:
        """
        Return True if hit_count is too low and we should fall back to unfiltered.

        Args:
            hit_count: number of filtered search results
            category: category name (for logging)

        Returns:
            True if should fall back to unfiltered search
        """
        if hit_count < MIN_CATEGORY_HITS:
            logger.warning(
                f"[MetadataFilter] Category '{category}' returned only {hit_count} hits, "
                f"falling back to unfiltered search"
            )
            return True
        return False
