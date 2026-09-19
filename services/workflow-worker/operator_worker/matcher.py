"""Deterministic token-overlap matcher for requirement-to-evidence scoring.

No model calls, no external dependencies — uses only the Python standard library.
Results are fully reproducible from stored inputs.

Scoring:
    Jaccard similarity = |tokens(req) ∩ tokens(evidence)| / |tokens(req) ∪ tokens(evidence)|

Decision thresholds:
    >= SUPPORTED_THRESHOLD  →  "supported"
    >= PARTIAL_THRESHOLD    →  "partial"
    <  PARTIAL_THRESHOLD    →  "missing"

The thresholds are module-level constants so tests can override them.
"""

from __future__ import annotations

import re

# ── Match-tier thresholds ──────────────────────────────────────────────────
SUPPORTED_THRESHOLD = 0.40   # Jaccard ≥ this → supported
PARTIAL_THRESHOLD   = 0.15   # Jaccard ≥ this → partial

# ── Contribution of a partial match to the weighted fit score ──────────────
PARTIAL_WEIGHT = 0.40        # partial counts as 40 % of a full match

# ── Stopwords to remove before tokenising ─────────────────────────────────
_STOPWORDS = frozenset(
    """a an the and or but if in on at to for of with by from as is are
    was were be been being have has had do does did will would could should
    may might must can its it this that these those we our you your they
    their all any some no not nor so yet both either neither one two three
    four five more most than then such only also just even new good
    strong work experience knowledge using ability skills skill required
    preferred plus bonus nice to have proficiency familiarity understanding
    background demonstrated proven solid excellent""".split()
)

# Suffixes to strip (order matters — longest first).
_SUFFIXES = ("ment", "tion", "ations", "ings", "ing", "tion", "ed", "er", "ers", "ly", "al", "ity", "s")


def _stem(word: str) -> str:
    """Very lightweight suffix stripping so plurals and gerunds normalise."""
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: len(word) - len(suffix)]
    return word


def tokenize(text: str) -> frozenset[str]:
    """Return a frozenset of meaningful stemmed lowercase tokens from *text*.

    Splits on any non-alphanumeric character (handles camelCase via +/# etc.),
    removes short tokens and English stopwords, then applies lightweight suffix
    stripping.
    """
    raw = re.split(r"[^a-zA-Z0-9]+", text.lower())
    tokens = set()
    for tok in raw:
        if len(tok) < 2:
            continue
        # Preserve well-known short tech tokens.
        if tok in {"go", "r", "c", "ui", "ux", "ml", "ai", "ci", "cd", "qa"}:
            tokens.add(tok)
            continue
        if tok in _STOPWORDS:
            continue
        tokens.add(_stem(tok))
    return frozenset(tokens)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Return the Jaccard similarity between two token sets.

    Returns 0.0 when both sets are empty.
    """
    if not a and not b:
        return 0.0
    union = a | b
    return len(a & b) / len(union)


def score_requirement(
    req_tokens: frozenset[str],
    evidence_chunks,  # Iterable of Evidence-like objects with .text and .skills
    skill_names: frozenset[str] | None = None,
) -> tuple[str, float, list[str]]:
    """Return (status, best_jaccard, evidence_ids) for a single requirement.

    Skill-list exact match (case-insensitive) short-circuits to 'supported'
    so existing fixture tests are unaffected.

    Arguments:
        req_tokens:      tokenized requirement text
        evidence_chunks: iterable of Evidence objects
        skill_names:     tokenized set of requirement skill-name tokens for
                         the fast exact-skill path (may be None)
    """
    best_score = 0.0
    supported_ids: list[str] = []
    partial_ids: list[str] = []

    req_text_lower: frozenset[str] = req_tokens

    for evidence in evidence_chunks:
        # ── Fast path: exact skill-list match ─────────────────────────────
        evidence_skills_lower = {s.casefold() for s in evidence.skills}
        if skill_names and skill_names & evidence_skills_lower:
            # At least one req token exactly matches a skill label → supported
            supported_ids.append(evidence.id)
            best_score = 1.0
            continue

        # ── Token-overlap path ─────────────────────────────────────────────
        ev_tokens = tokenize(evidence.text)
        sim = jaccard(req_text_lower, ev_tokens)
        if sim >= SUPPORTED_THRESHOLD:
            supported_ids.append(evidence.id)
            if sim > best_score:
                best_score = sim
        elif sim >= PARTIAL_THRESHOLD:
            partial_ids.append(evidence.id)
            if sim > best_score:
                best_score = sim

    if supported_ids:
        return "supported", best_score, supported_ids
    if partial_ids:
        return "partial", best_score, partial_ids
    return "missing", best_score, []
