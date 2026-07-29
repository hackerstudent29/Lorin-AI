"""
SpellCorrector — Requirement 7 compliant token-level spell corrector.
Uses Levenshtein edit distance against known MSAJCE vocabulary.
"""
import pickle, re, time, logging
from pathlib import Path
from collections import defaultdict, Counter

logger = logging.getLogger(__name__)

VOCAB_PATH = Path("bm25_index/vocab.pkl")

SPELL_MIN_FREQ      = 1
SPELL_MAX_EDIT_DIST = 2
SPELL_TIMEOUT_MS    = 200  # Warn if correction takes over 200ms

# Common English words that should NEVER be spell-corrected
_COMMON_WORDS = frozenset({
    "hello", "help", "please", "thank", "thanks", "okay", "good",
    "what", "when", "where", "which", "while", "about", "after",
    "also", "back", "been", "before", "best", "both", "came",
    "come", "could", "does", "done", "each", "even", "ever",
    "from", "gave", "give", "goes", "gone", "have", "here",
    "high", "into", "just", "keep", "kind", "know", "last",
    "left", "like", "list", "long", "look", "made", "make",
    "many", "more", "most", "move", "much", "must", "name",
    "need", "next", "note", "only", "open", "over", "part",
    "past", "plan", "play", "said", "same", "show", "side",
    "some", "soon", "such", "sure", "take", "than", "that",
    "them", "then", "they", "this", "time", "told", "took",
    "turn", "used", "very", "want", "ways", "well", "went",
    "were", "will", "with", "work", "year", "your", "college",
    "tell", "show", "give", "list", "what", "does", "have",
})


class SpellCorrector:
    """
    Token-level spell corrector backed by a vocabulary built from all
    chunk text tokens in the Qdrant corpus plus static MSAJCE proper nouns.
    """

    STATIC_VOCAB = [
        "msajce", "admission", "placement", "hostel", "transport",
        "incubation", "iqac", "nirf", "alumni", "library",
        "cse", "ece", "eee", "csbs", "aiml", "aids", "cyber",
        "btech", "mtech", "mba", "barch", "beng",
        "tuition", "scholarship", "syllabus", "semester", "faculty",
        "laboratory", "department", "engineering", "technology",
        "institute", "university", "research", "campus", "student",
        "ranking", "accreditation", "affiliation", "autonomy",
        "facilities", "infrastructure", "accommodation",
        "velachery", "guindy", "kathipara", "tharamani", "medavakkam",
        "pallikaranai", "thoraipakkam", "ennore", "porur", "nemilichery",
        "uthiramerur", "moolakadai", "icf", "chunambedu", "sholinganallur",
        "siruseri", "kelambakkam", "padur", "perungudi", "karapakkam",
        "adambakkam", "perumbakkam", "kovilampakkam", "madipakkam",
    ]

    def __init__(self, vocab=None):
        if vocab is not None:
            self._vocab = vocab
        elif VOCAB_PATH.exists():
            try:
                with open(VOCAB_PATH, "rb") as f:
                    self._vocab = pickle.load(f)
                logger.info(f"[SpellCorrector] Loaded vocab ({len(self._vocab)} terms).")
            except Exception as e:
                logger.warning(f"[SpellCorrector] Failed to load vocab: {e}. Using static only.")
                self._vocab = {}
        else:
            self._vocab = {}

        for word in self.STATIC_VOCAB:
            self._vocab.setdefault(word, 999)

        # Build two-char prefix + length index for O(1) candidate lookup
        # Structure: {(first2chars, length): [word, ...]}
        self._prefix_len_index: dict = defaultdict(list)
        for word, freq in self._vocab.items():
            if freq >= SPELL_MIN_FREQ and len(word) >= 3:
                self._prefix_len_index[(word[:2], len(word))].append(word)

    @classmethod
    def build_from_texts(cls, texts) -> "SpellCorrector":
        TOKEN_RE = re.compile(r"[a-zA-Z]{3,}")
        counts: Counter = Counter()
        for text in texts:
            counts.update(TOKEN_RE.findall(text.lower()))
        vocab = dict(counts)
        Path("bm25_index").mkdir(exist_ok=True)
        with open(VOCAB_PATH, "wb") as f:
            pickle.dump(vocab, f)
        logger.info(f"[SpellCorrector] Built vocab from {len(texts)} texts ({len(vocab)} unique tokens).")
        return cls(vocab)

    @staticmethod
    def _is_skip_token(token: str) -> bool:
        if re.fullmatch(r"\d+", token):
            return True
        if re.match(r"https?://|www\.", token):
            return True
        if len(token) <= 2:
            return True
        if token.lower() in _COMMON_WORDS:
            return True
        return False

    def _best_candidate(self, token: str):
        try:
            from Levenshtein import distance as lev
        except ImportError:
            return None

        t = token.lower()
        if t in self._vocab:
            return None

        best_word = None
        best_dist = 3
        t_len = len(t)
        t2 = t[:2]

        # Collect candidates with hard cap to keep it fast
        candidate_set = set()
        for delta in range(SPELL_MAX_EDIT_DIST + 1):
            for length in [t_len + delta, t_len - delta]:
                if length < 3:
                    continue
                candidate_set.update(self._prefix_len_index.get((t2, length), []))
                if t_len >= 4:
                    candidate_set.update(self._prefix_len_index.get((t[0] + t[2], length), []))
            if len(candidate_set) > 200:  # hard cap — avoid slow scan
                break

        for word in candidate_set:
            d = lev(t, word)
            if d <= SPELL_MAX_EDIT_DIST and d < best_dist:
                best_dist = d
                best_word = word
        return best_word

    def correct(self, query: str):
        t0 = time.monotonic()
        tokens = query.split()
        corrections = []
        result_tokens = []

        for tok in tokens:
            if self._is_skip_token(tok):
                result_tokens.append(tok)
                continue
            candidate = self._best_candidate(tok)
            if candidate and candidate != tok.lower():
                corrections.append((tok, candidate))
                result_tokens.append(candidate)
                logger.debug(f"[SpellCorrector] '{tok}' -> '{candidate}'")
            else:
                result_tokens.append(tok)

        elapsed_ms = (time.monotonic() - t0) * 1000
        if elapsed_ms > SPELL_TIMEOUT_MS:
            logger.warning(f"[SpellCorrector] took {elapsed_ms:.1f}ms for {len(tokens)} tokens")

        return " ".join(result_tokens), corrections
