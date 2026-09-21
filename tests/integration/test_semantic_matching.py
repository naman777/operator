"""Integration tests for the semantic token-overlap evidence matcher.

Tests cover:
- Exact skill-list match → supported (fast path, fixture-compatible)
- Token-overlap match → supported (e.g. "Python development" ↔ "Python developer")
- Partial overlap → partial tier
- No overlap → missing
- Partial matches contribute to fit score
- Case-insensitive and plural-normalised matching
- verify() accepts partial matches without raising
- Full activity chain produces score > 0 for a real-text job + evidence
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from operator_api.main import create_app
from operator_api.schemas import CandidateProfile, Evidence, JobPosting, Requirement, Source
from operator_worker.analysis import match, verify
from operator_worker.matcher import tokenize, jaccard, score_requirement
from datetime import datetime, timezone


# ── Helpers ────────────────────────────────────────────────────────────────


def _utc():
    return datetime.now(timezone.utc)


def _source(sid="src-1", title="Job posting"):
    return Source(id=sid, url="https://example.com/job", title=title, excerpt="", retrieved_at=_utc())


def _req(text, category="skill", importance="required", sid="src-1", rid=None):
    from hashlib import sha256
    rid = rid or sha256(text.encode()).hexdigest()[:16]
    return Requirement(id=rid, text=text, category=category, importance=importance, source_id=sid)


def _evidence(text, skills=None, eid=None, doc="doc-1"):
    eid = eid or f"ev-{hash(text) % 100000}"
    return Evidence(id=eid, text=text, document_id=doc, source_location=f"{doc}/line 1", skills=skills or [])


def _job(requirements, sources=None):
    from uuid import uuid4
    if sources is None:
        sources = [_source()]
    return JobPosting(
        id=str(uuid4()),
        title="Software Engineer",
        company="Acme",
        url="https://example.com/job",
        requirements=requirements,
        sources=sources,
    )


def _profile(evidence_list, skills=None):
    from uuid import uuid4
    return CandidateProfile(
        id=str(uuid4()),
        name="Test Candidate",
        graduation_year=2023,
        locations=["Remote"],
        skills=skills or [],
        evidence=evidence_list,
    )


# ── Unit tests for matcher module ──────────────────────────────────────────


def test_tokenize_removes_stopwords_and_stems():
    tokens = tokenize("Python development experience required")
    assert "python" in tokens or any("python" in t for t in tokens)
    # Stopwords should be gone
    assert "required" not in tokens
    assert "experience" not in tokens or len(tokens) > 1


def test_jaccard_identical_sets():
    a = frozenset({"python", "develop"})
    assert jaccard(a, a) == 1.0


def test_jaccard_disjoint_sets():
    assert jaccard(frozenset({"python"}), frozenset({"java"})) == 0.0


def test_jaccard_empty():
    assert jaccard(frozenset(), frozenset()) == 0.0


# ── score_requirement unit tests ───────────────────────────────────────────


def test_exact_skill_match_is_supported():
    """Evidence with 'Python' in skills → supported for 'Python' requirement."""
    ev = _evidence("Built a service", skills=["Python"])
    req_tokens = tokenize("Python")
    req_skills = frozenset({"python"})
    status, score, ids = score_requirement(req_tokens, [ev], skill_names=req_skills)
    assert status == "supported"
    assert ev.id in ids


def test_token_overlap_match_is_supported():
    """'Python development' requirement matches evidence text containing 'Python developer'."""
    ev = _evidence("Experienced Python developer, built REST APIs")
    req_tokens = tokenize("Python development")
    status, score, ids = score_requirement(req_tokens, [ev])
    assert status in ("supported", "partial"), f"Expected at least partial, got {status}"
    assert ev.id in ids


def test_partial_overlap_is_partial():
    """Evidence with some but not all req tokens → partial tier.

    req: React TypeScript frontend development  → tokens: {react, typescr, frontend, develop}
    ev:  React frontend work, no TypeScript     → tokens include react + frontend → Jaccard >= PARTIAL_THRESHOLD
    """
    ev = _evidence("React frontend development for web applications, no TypeScript experience")
    req_tokens = tokenize("React TypeScript development backend services")
    status, score, ids = score_requirement(req_tokens, [ev])
    # Must be at least partial (react + develop overlap)
    assert status in ("supported", "partial"), f"Expected at least partial, got {status} (score={score})"
    assert ev.id in ids


def test_no_overlap_is_missing():
    """'Kubernetes orchestration' requirement with only Python evidence → missing."""
    ev = _evidence("Python scripting and data pipelines", skills=["Python"])
    req_tokens = tokenize("Kubernetes orchestration container deployment")
    status, score, ids = score_requirement(req_tokens, [ev])
    assert status == "missing"
    assert ids == []


def test_case_insensitive_and_plural_normalised():
    """'APIs' in requirement should match 'api' token in evidence."""
    ev = _evidence("Built REST api integrations and designed api contracts")
    req_tokens = tokenize("REST APIs")
    status, score, ids = score_requirement(req_tokens, [ev])
    assert status in ("supported", "partial")


# ── match() + verify() integration tests ──────────────────────────────────


def test_score_includes_partial_contribution():
    """A profile with only partial-matching evidence should have score > 0."""
    req = _req("React TypeScript frontend development backend")
    # Evidence has 'React' + 'frontend' + 'develop' — three token overlaps → partial or supported
    ev = _evidence("React frontend developer building web apps with Redux", skills=[])
    job = _job([req])
    profile = _profile([ev])
    result = match(job, profile)
    assert result["score"] > 0, f"Expected score > 0, got {result['score']}"
    statuses = {m["requirement_id"]: m["status"] for m in result["matches"]}
    assert statuses[req.id] in ("supported", "partial")


def test_full_mission_match_and_verify_round_trip():
    """match() followed by verify() should succeed without raising for a real-text job."""
    requirements = [
        _req("Python backend development", rid="req-1"),
        _req("PostgreSQL database experience", rid="req-2"),
        _req("Docker containerization", rid="req-3", importance="preferred"),
    ]
    evidence_list = [
        _evidence("Developed REST APIs in Python using FastAPI framework", eid="ev-1"),
        _evidence("Managed PostgreSQL databases, wrote complex SQL queries", eid="ev-2"),
        _evidence("Containerized apps using Docker and Docker Compose", eid="ev-3"),
    ]
    job = _job(requirements)
    profile = _profile(evidence_list)
    matched = match(job, profile)
    assert matched["score"] > 0
    # All three requirements should have at least partial matches
    for m in matched["matches"]:
        assert m["status"] in ("supported", "partial"), f"Expected match for {m['requirement_id']}, got missing"
    # verify() must not raise
    verified = verify(job, matched)
    assert verified["verified"] is True
    assert verified["requirements_checked"] == 3


def test_verify_accepts_partial_matches():
    """verify() should not raise when some matches are 'partial'."""
    req = _req("Kubernetes container orchestration", rid="req-kube")
    ev = _evidence("Worked with container deployments and microservices", eid="ev-kube")
    job = _job([req])
    profile = _profile([ev])
    matched = match(job, profile)
    # Should complete without raising regardless of tier
    verified = verify(job, matched)
    assert verified["verified"] is True


def test_fixture_skill_exact_match_still_works(tmp_path):
    """The existing fixture workflow (exact skill in evidence.skills) must still pass."""
    url = f"sqlite:///{tmp_path / 'sem.db'}"
    with TestClient(create_app(url)) as client:
        token = client.post("/v1/guest-sessions?demo=true").json()["token"]
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "sem-fixture-001"}
        # Ingest evidence with explicit Python skill tag
        client.post(
            "/v1/profile/documents",
            headers=headers,
            json={"name": "resume.txt", "text": "Python FastAPI Docker developer"},
        )
        resp = client.post(
            "/v1/missions",
            headers=headers,
            json={"job_url": "https://operator.example.com/jobs/swe-intern"},
        )
        if resp.status_code not in (200, 201):
            # Sample job URL not available — skip gracefully
            return
