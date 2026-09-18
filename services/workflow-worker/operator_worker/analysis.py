"""Deterministic fixture matching. This is not semantic/model-based analysis."""

from operator_api.schemas import CandidateProfile, JobPosting, MissionResult, RequirementMatch


def match(job: JobPosting, profile: CandidateProfile):
    matches = []
    numerator = denominator = 0
    for requirement in job.requirements:
        ids = [
            e.id for e in profile.evidence if requirement.text.casefold() in {s.casefold() for s in e.skills}
        ]
        supported = requirement.category == "skill" and bool(ids)
        weight = 2 if requirement.importance == "required" else 1
        numerator += weight if supported else 0
        denominator += weight
        matches.append(
            RequirementMatch(
                requirement_id=requirement.id,
                status="supported" if supported else "missing",
                evidence_ids=ids if supported else [],
                explanation="Exact skill match in stored synthetic candidate evidence."
                if supported
                else "No supporting candidate evidence was found by the fixture matcher.",
            )
        )
    # A matching location is not sufficient to establish work authorization or all eligibility constraints.
    eligibility = "unknown"
    if job.location and job.location.casefold() not in {
        location.casefold() for location in profile.locations
    }:
        eligibility = "ineligible"
    return {
        "matches": [m.model_dump(mode="json") for m in matches],
        "score": round(100 * numerator / denominator, 2) if denominator else 0,
        "eligibility": eligibility,
        "profile": profile.model_dump(mode="json"),
    }


def verify(job: JobPosting, matched: dict):
    profile = CandidateProfile.model_validate(matched["profile"])
    sources = {source.id for source in job.sources}
    requirements = {r.id: r for r in job.requirements}
    evidence = {e.id: e for e in profile.evidence}
    matches = [RequirementMatch.model_validate(m) for m in matched["matches"]]
    if len(requirements) != len(job.requirements) or len(evidence) != len(profile.evidence):
        raise ValueError("Duplicate provenance IDs")
    if len(matches) != len(requirements) or {m.requirement_id for m in matches} != set(requirements):
        raise ValueError("Requirement coverage mismatch")
    if any(r.source_id not in sources for r in job.requirements):
        raise ValueError("Missing job source")
    for m in matches:
        if m.status != "missing" and not m.evidence_ids:
            raise ValueError("Unsupported positive match")
        for eid in m.evidence_ids:
            if eid not in evidence or requirements[m.requirement_id].text.casefold() not in {
                skill.casefold() for skill in evidence[eid].skills
            }:
                raise ValueError("Evidence does not support the match")
    expected = match(job, profile)
    if any(matched[key] != expected[key] for key in ("score", "eligibility", "matches")):
        raise ValueError("Stored match does not reproduce the fixture rubric")
    return {"verified": True, "requirements_checked": len(matches), "source_ids": sorted(sources)}


def result(mission_id, matched, verified):
    return MissionResult(
        mission_id=mission_id,
        eligibility=matched["eligibility"],
        score=matched["score"],
        matches=matched["matches"],
        source_ids=verified["source_ids"],
        artifact_ids=[],
    ).model_dump(mode="json")
