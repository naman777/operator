"""Requirement matching and mission result assembly.

match()  – token-overlap soft matcher; exact skill-list match short-circuits
           to 'supported' so fixture evidence is unaffected.
verify() – provenance checks; accepts 'partial' in addition to 'supported'.
result() – assembles the final MissionResult from matched/verified outputs.
"""

from operator_api.schemas import (
    CandidateProfile,
    CompanyResearch,
    EligibilityCheck,
    JobPosting,
    MissionResult,
    RequirementMatch,
)

from .eligibility import evaluate
from .matcher import PARTIAL_WEIGHT, score_requirement, tokenize


def match(job: JobPosting, profile: CandidateProfile):
    matches = []
    numerator = denominator = 0.0
    for requirement in job.requirements:
        req_tokens = tokenize(requirement.text)
        # Pass the requirement text as a single-token skill name so the exact
        # skill-list fast path can fire when the evidence skills list already
        # contains the verbatim requirement text (fixture data).
        req_skill_names = frozenset({requirement.text.casefold()})
        status, best_score, evidence_ids = score_requirement(
            req_tokens, profile.evidence, skill_names=req_skill_names
        )
        weight = 2.0 if requirement.importance == "required" else 1.0
        if status == "supported":
            contribution = weight
            explanation = (
                f"Token-overlap match (Jaccard {best_score:.2f}); "
                f"requirement is fully supported by stored candidate evidence."
            )
        elif status == "partial":
            contribution = weight * PARTIAL_WEIGHT
            explanation = (
                f"Partial token-overlap (Jaccard {best_score:.2f}); "
                f"requirement is partially supported — manual review recommended."
            )
        else:
            contribution = 0.0
            explanation = "No supporting candidate evidence was found."
        numerator += contribution
        denominator += weight
        matches.append(
            RequirementMatch(
                requirement_id=requirement.id,
                status=status,
                evidence_ids=evidence_ids,
                explanation=explanation,
            )
        )
    eligibility, eligibility_checks = evaluate(job, profile)
    return {
        "matches": [m.model_dump(mode="json") for m in matches],
        "score": round(100 * numerator / denominator, 2) if denominator else 0.0,
        "eligibility": eligibility,
        "eligibility_checks": eligibility_checks,
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
        # Both 'supported' and 'partial' matches must reference real evidence IDs.
        if m.status in ("supported", "partial") and not m.evidence_ids:
            raise ValueError("Unsupported positive match")
        for eid in m.evidence_ids:
            if eid not in evidence:
                raise ValueError("Evidence ID not found in profile")
    # Re-run match() deterministically to confirm stored result is reproducible.
    expected = match(job, profile)
    if any(
        matched.get(key) != expected.get(key)
        for key in ("score", "eligibility", "eligibility_checks")
    ):
        raise ValueError("Stored match does not reproduce the deterministic rubric")
    expected_matches = {item["requirement_id"]: item for item in expected["matches"]}
    for item in matches:
        deterministic = expected_matches[item.requirement_id]
        if item.status != deterministic["status"] or sorted(item.evidence_ids) != sorted(
            deterministic["evidence_ids"]
        ):
            raise ValueError("Stored match does not reproduce the deterministic evidence matrix")
    return {"verified": True, "requirements_checked": len(matches), "source_ids": sorted(sources)}


def result(mission_id, matched, verified, researched=None):
    return MissionResult(
        mission_id=mission_id,
        eligibility=matched["eligibility"],
        eligibility_checks=[
            EligibilityCheck.model_validate(c) for c in matched.get("eligibility_checks", [])
        ],
        score=matched["score"],
        matches=matched["matches"],
        source_ids=verified["source_ids"],
        company_research=CompanyResearch.model_validate(researched) if researched else None,
        artifact_ids=[],
    ).model_dump(mode="json")
