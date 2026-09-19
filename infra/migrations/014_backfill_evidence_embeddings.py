"""Migration 014: backfill vectors for evidence ingested before migration 013."""

import hashlib
import math
import re

from sqlalchemy import MetaData, Table, select

DIMENSIONS = 256


def embed(text):
    tokens = re.findall(r"[a-z0-9+#.]+", text.casefold())
    features = [*tokens, *(f"{a}:{b}" for a, b in zip(tokens, tokens[1:]))]
    vector = [0.0] * DIMENSIONS
    for feature in features:
        digest = hashlib.sha256(feature.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % DIMENSIONS
        vector[index] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


def upgrade(connection):
    metadata = MetaData()
    profiles = Table("profiles", metadata, autoload_with=connection)
    documents = Table("profile_documents", metadata, autoload_with=connection)
    chunks = Table("evidence_chunks", metadata, autoload_with=connection)
    document_ids = set(connection.execute(select(documents.c.id)).scalars())
    indexed = set(connection.execute(select(chunks.c.id)).scalars())
    rows = []
    for workspace_id, content in connection.execute(select(profiles.c.workspace_id, profiles.c.content)):
        for item in (content or {}).get("evidence", []):
            if item.get("id") in indexed or item.get("document_id") not in document_ids:
                continue
            text = item.get("text", "")
            skills = item.get("skills", [])
            rows.append(
                {
                    "id": item["id"],
                    "workspace_id": workspace_id,
                    "document_id": item["document_id"],
                    "text": text,
                    "source_location": item.get("source_location", "unknown"),
                    "skills": skills,
                    "embedding": embed(text + " " + " ".join(skills)),
                }
            )
    if rows:
        connection.execute(chunks.insert(), rows)
