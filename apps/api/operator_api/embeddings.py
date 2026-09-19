"""Deterministic feature-hash embeddings and dialect-aware evidence retrieval."""

import hashlib
import math
import re

from sqlalchemy import select

from .db import EvidenceChunk

DIMENSIONS = 256


def embed(text: str) -> list[float]:
    tokens = re.findall(r"[a-z0-9+#.]+", text.casefold())
    features = [*tokens, *(f"{a}:{b}" for a, b in zip(tokens, tokens[1:]))]
    vector = [0.0] * DIMENSIONS
    for feature in features:
        digest = hashlib.sha256(feature.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % DIMENSIONS
        vector[index] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


def cosine(left, right) -> float:
    return sum(float(a) * float(b) for a, b in zip(left, right))


def relevant_ids(db, workspace_id: str, queries: list[str], limit_per_query: int = 5) -> list[str]:
    if not queries:
        return []
    ids = []
    if db.bind.dialect.name == "postgresql":
        for query in queries:
            rows = db.scalars(
                select(EvidenceChunk.id)
                .where(EvidenceChunk.workspace_id == workspace_id)
                .order_by(EvidenceChunk.embedding.cosine_distance(embed(query)))
                .limit(limit_per_query)
            ).all()
            ids.extend(rows)
    else:
        rows = db.scalars(select(EvidenceChunk).where(EvidenceChunk.workspace_id == workspace_id)).all()
        for query in queries:
            vector = embed(query)
            ranked = sorted(rows, key=lambda row: cosine(row.embedding, vector), reverse=True)
            ids.extend(row.id for row in ranked[:limit_per_query])
    return list(dict.fromkeys(ids))
