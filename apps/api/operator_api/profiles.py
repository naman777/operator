"""Plain-text ingestion preserves excerpts; it never infers accomplishments or education."""

import hashlib
import re
from uuid import uuid4
from sqlalchemy import select, update
from .db import ProfileDocument, StoredProfile, Workspace
from .schemas import CandidateProfile, Evidence

SKILLS = (
    "Python",
    "TypeScript",
    "JavaScript",
    "React",
    "SQL",
    "PostgreSQL",
    "FastAPI",
    "Docker",
    "PyTorch",
    "Redis",
    "Temporal",
)


def load(db, workspace_id, fallback):
    stored = db.get(StoredProfile, workspace_id)
    return CandidateProfile.model_validate(stored.content) if stored else fallback()


def lock(db, workspace_id):
    db.execute(update(Workspace).where(Workspace.id == workspace_id).values(name=Workspace.name))


def ingest(db, workspace_id, body, fallback):
    lock(db, workspace_id)
    checksum = hashlib.sha256(body.text.encode("utf-8")).hexdigest()
    existing = db.scalar(
        select(ProfileDocument).where(
            ProfileDocument.workspace_id == workspace_id, ProfileDocument.checksum == checksum
        )
    )
    stored = db.get(StoredProfile, workspace_id)
    profile = load(db, workspace_id, fallback)
    if existing:
        return {
            "document_id": existing.id,
            "evidence_count": sum(e.document_id == existing.id for e in profile.evidence),
            "profile_version": stored.version if stored else 0,
        }
    document = ProfileDocument(
        id=str(uuid4()), workspace_id=workspace_id, checksum=checksum, name=body.name, text=body.text
    )
    db.add(document)
    chunks = []
    for line_number, line in enumerate(body.text.splitlines(), 1):
        text = line.strip()
        if not text:
            continue
        for offset in range(0, len(text), 1500):
            excerpt = text[offset : offset + 1500]
            skills = [
                skill
                for skill in SKILLS
                if re.search(r"(?<!\w)" + re.escape(skill) + r"(?!\w)", excerpt, re.I)
            ]
            chunks.append(
                Evidence(
                    id=f"{document.id}:{line_number}:{offset}",
                    text=excerpt,
                    document_id=document.id,
                    source_location=f"{body.name} / line {line_number} / characters {offset}-{offset + len(excerpt)}",
                    skills=skills,
                )
            )
    if not chunks:
        raise ValueError("Document must contain non-whitespace text")
    profile.evidence.extend(chunks)
    profile.skills = sorted(set(profile.skills) | {skill for chunk in chunks for skill in chunk.skills})
    if stored:
        stored.content = profile.model_dump(mode="json")
        stored.version += 1
    else:
        stored = StoredProfile(workspace_id=workspace_id, content=profile.model_dump(mode="json"), version=1)
        db.add(stored)
    return {"document_id": document.id, "evidence_count": len(chunks), "profile_version": stored.version}
