"""Plain-text ingestion with heuristic structured parsing.

Ingestion preserves source excerpts and never infers accomplishments.
Structured fields (graduation year, experience years) are extracted only
by deterministic regex patterns; uncertain values are left as None.
"""

import hashlib
import re
from uuid import uuid4
from sqlalchemy import select, update
from .db import EvidenceChunk, ProfileDocument, StoredProfile, Workspace
from .embeddings import embed, relevant_ids
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

# ── Heuristic patterns for structured resume fields ──────────────────────────

# Education section headers
_EDUCATION_HEADER = re.compile(
    r"^(education|academic\s+background|qualifications?)\s*:?\s*$",
    re.I | re.M,
)

# Graduation year: "Class of 2025", "Expected 2025", "Graduated 2024", "May 2024", four-digit year in degree line
_GRAD_YEAR = re.compile(
    r"\b(?:class\s+of|expected|graduating|graduated(?:\s+in)?|expected\s+graduation|grad\.?)\s*:?\s*(20\d{2}|19[89]\d)\b"
    r"|(20\d{2}|19[89]\d)\s*(?:\(expected\)|\(anticipated\))?",
    re.I,
)

# Experience section headers
_EXPERIENCE_HEADER = re.compile(
    r"^(work\s+experience|professional\s+experience|employment(\s+history)?|experience)\s*:?\s*$",
    re.I | re.M,
)

# Employment date range: "Jan 2020 – Mar 2023", "2019 - 2022", "06/2021 - Present", "2020 – present"
_DATE_RANGE = re.compile(
    r"(?:"
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"\.?\s+)?"
    r"(20\d{2}|19[89]\d)"
    r"\s*(?:–|-|to)\s*"
    r"(?:(20\d{2}|19[89]\d)|(?:present|current|now))",
    re.I,
)


def _parse_grad_year(text: str) -> int | None:
    """Return the most recently mentioned graduation year, or None."""
    candidates = []
    for m in _GRAD_YEAR.finditer(text):
        year_str = m.group(1) or m.group(2)
        if year_str:
            candidates.append(int(year_str))
    if not candidates:
        return None
    # Prefer years in an education section if detectable
    edu_match = _EDUCATION_HEADER.search(text)
    if edu_match:
        edu_text = text[edu_match.start():]
        exp_match = _EXPERIENCE_HEADER.search(edu_text)
        edu_section = edu_text[: exp_match.start()] if exp_match else edu_text[:3000]
        section_candidates = []
        for m in _GRAD_YEAR.finditer(edu_section):
            year_str = m.group(1) or m.group(2)
            if year_str:
                section_candidates.append(int(year_str))
        if section_candidates:
            return max(section_candidates)
    return max(candidates)


def _parse_experience_years(text: str) -> float | None:
    """Return total years of experience inferred from date ranges, or None."""
    from datetime import date as _date

    today = _date.today()
    total_months = 0
    found_any = False

    # Restrict to experience section if present
    exp_match = _EXPERIENCE_HEADER.search(text)
    region = text[exp_match.start():] if exp_match else text

    for m in _DATE_RANGE.finditer(region):
        found_any = True
        start_year = int(m.group(1))
        end_group = m.group(2)
        end_year = int(end_group) if end_group else today.year
        # Treat each role as starting January of start_year, ending December of end_year
        months = max(0, (end_year - start_year) * 12)
        total_months += months

    if not found_any or total_months == 0:
        return None
    # Round to one decimal place; cap at 40 to guard against malformed text
    return min(40.0, round(total_months / 12, 1))


def _parse_structure(text: str) -> dict:
    """Return a dict of inferred structured fields from plain resume text.

    Only fields that can be extracted with reasonable confidence are included.
    Returns an empty dict when nothing is found.
    """
    result = {}
    grad_year = _parse_grad_year(text)
    if grad_year and 1980 <= grad_year <= 2030:
        result["graduation_year"] = grad_year
    exp = _parse_experience_years(text)
    if exp is not None:
        result["experience_years"] = exp
    return result


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
    db.flush()
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

    # Apply heuristic structural fields only if they improve on the current values.
    parsed = _parse_structure(body.text)
    updated_parse_source = profile.parse_source
    if "graduation_year" in parsed and profile.parse_source not in ("user-correction",):
        profile = profile.model_copy(update={"graduation_year": parsed["graduation_year"]})
        updated_parse_source = "heuristic-v1"
    if "experience_years" in parsed and profile.experience_years is None:
        profile = profile.model_copy(update={"experience_years": parsed["experience_years"]})
        updated_parse_source = "heuristic-v1"
    if updated_parse_source != profile.parse_source:
        profile = profile.model_copy(update={"parse_source": updated_parse_source})

    if stored:
        stored.content = profile.model_dump(mode="json")
        stored.version += 1
    else:
        stored = StoredProfile(workspace_id=workspace_id, content=profile.model_dump(mode="json"), version=1)
        db.add(stored)
    for chunk in chunks:
        db.add(
            EvidenceChunk(
                id=chunk.id,
                workspace_id=workspace_id,
                document_id=chunk.document_id,
                text=chunk.text,
                source_location=chunk.source_location,
                skills=chunk.skills,
                embedding=embed(chunk.text + " " + " ".join(chunk.skills)),
            )
        )
    return {"document_id": document.id, "evidence_count": len(chunks), "profile_version": stored.version}


def retrieve(db, workspace_id, profile, requirements, limit_per_query=5):
    ids = relevant_ids(db, workspace_id, [item.text for item in requirements], limit_per_query)
    if not ids:
        return profile
    by_id = {item.id: item for item in profile.evidence}
    evidence = [by_id[item_id] for item_id in ids if item_id in by_id]
    return profile.model_copy(update={"evidence": evidence}) if evidence else profile


def remove_evidence(db, workspace_id, evidence_id, expected_version, fallback):
    lock(db, workspace_id)
    stored = db.get(StoredProfile, workspace_id, populate_existing=True)
    version = stored.version if stored else 0
    if version != expected_version:
        raise RuntimeError("Profile changed. Reload before deleting evidence.")
    profile = load(db, workspace_id, fallback)
    if all(item.id != evidence_id for item in profile.evidence):
        raise LookupError("Evidence not found")
    updated = profile.model_copy(
        update={"evidence": [item for item in profile.evidence if item.id != evidence_id]}
    )
    indexed = db.scalar(
        select(EvidenceChunk).where(
            EvidenceChunk.id == evidence_id, EvidenceChunk.workspace_id == workspace_id
        )
    )
    if indexed:
        db.delete(indexed)
    if stored:
        stored.content = updated.model_dump(mode="json")
        stored.version += 1
    else:
        stored = StoredProfile(
            workspace_id=workspace_id, content=updated.model_dump(mode="json"), version=1
        )
        db.add(stored)
    return {"profile": updated, "version": stored.version}
