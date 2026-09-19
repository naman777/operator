"""Produce reviewable drafts using only the completed run's stored evidence."""

from sqlalchemy import select
from .db import MissionStep, StepOutput
from .schemas import (
    ArtifactCitation,
    ArtifactContent,
    CandidateProfile,
    CompanyResearch,
    JobPosting,
    MissionResult,
)


def checkpoint(db, mission_id, name):
    step = db.scalar(
        select(MissionStep).where(MissionStep.mission_id == mission_id, MissionStep.name == name)
    )
    if step is None or step.status != "completed":
        raise ValueError(f"Artifact generation requires the completed {name} checkpoint")
    output = db.get(StepOutput, step.id)
    if output is None or output.output is None:
        raise ValueError(f"Missing {name} output")
    return output.output


def prepare(db, mission_id, payload):
    payload = dict(payload)
    model_drafts = payload.pop("_model_drafts", None)
    payload.pop("_model_calls", None)
    report = MissionResult.model_validate(payload)
    if report.mission_id != mission_id or report.artifact_ids:
        raise ValueError("Invalid generation result identity")
    job_payload = dict(checkpoint(db, mission_id, "extracting"))
    job_payload.pop("_model_calls", None)
    job_payload.pop("_model_fallback", None)
    job = JobPosting.model_validate(job_payload)
    matched = checkpoint(db, mission_id, "matching")
    researched = CompanyResearch.model_validate(checkpoint(db, mission_id, "researching"))
    verified = checkpoint(db, mission_id, "verifying")
    if verified.get("verified") is not True:
        raise ValueError("Artifact generation requires verified evidence")
    for key in ("matches", "score", "eligibility", "eligibility_checks"):
        if report.model_dump(mode="json")[key] != matched.get(key, []):
            raise ValueError("Report does not match the stored analysis")
    if report.company_research != researched:
        raise ValueError("Company research does not match the stored checkpoint")
    source_ids = {source.id for source in job.sources}
    if set(report.source_ids) != source_ids or set(verified.get("source_ids", [])) != source_ids:
        raise ValueError("Report sources do not match the verified job")
    profile = CandidateProfile.model_validate(matched["profile"])
    requirements = {requirement.id: requirement for requirement in job.requirements}
    evidence = {item.id: item for item in profile.evidence}
    used = {}
    supported = []
    for match in report.matches:
        if match.requirement_id not in requirements:
            raise ValueError("Unknown requirement in generated report")
        if match.status == "supported":
            if not match.evidence_ids or any(eid not in evidence for eid in match.evidence_ids):
                raise ValueError("Unsupported artifact claim")
            supported.append((requirements[match.requirement_id], match))
            for eid in match.evidence_ids:
                used.setdefault(eid, []).append(match.requirement_id)
    citations = [
        ArtifactCitation(
            kind="job",
            reference_id=source.id,
            excerpt=source.excerpt,
            url=source.url,
            requirement_ids=[r.id for r in job.requirements if r.source_id == source.id],
        )
        for source in job.sources
    ]
    citations.extend(
        ArtifactCitation(
            kind="candidate",
            reference_id=eid,
            excerpt=evidence[eid].text,
            document_id=evidence[eid].document_id,
            source_location=evidence[eid].source_location,
            requirement_ids=requirement_ids,
        )
        for eid, requirement_ids in used.items()
    )
    if report.company_research:
        for company_source in report.company_research.sources:
            citations.append(
                ArtifactCitation(
                    kind="company",
                    reference_id=company_source.id,
                    excerpt=company_source.excerpt,
                    url=company_source.url,
                )
            )
    evidence_text = "\n\n".join(f"{evidence[eid].text} [{eid}]" for eid in used)
    evidence_paragraph = evidence_text or "I would appreciate the opportunity to learn more about the role."
    suggestions = [
        f"For {requirement.text}, foreground this existing evidence without adding achievements or metrics: "
        + " ".join(f"{evidence[eid].text} [{eid}]" for eid in match.evidence_ids)
        for requirement, match in supported
    ]
    if not suggestions:
        suggestions = [
            "No supported requirements were found. Add verified project evidence before tailoring the resume."
        ]
    preparation = []
    for match in report.matches:
        requirement = requirements[match.requirement_id]
        preparation.append(
            f"- {requirement.text}: "
            + (
                "prepare to explain the documented project evidence " + ", ".join(match.evidence_ids)
                if match.status == "supported"
                else "review this gap; do not claim experience that is not documented."
            )
        )
    if report.company_research and report.company_research.claims:
        preparation.append("\nCompany research (verify against cited official sources):")
        preparation.extend(
            f"- {claim.text} [{claim.source_id}]" for claim in report.company_research.claims
        )
    specs = {
        "cover_letter": ArtifactContent(
            text=f"Dear Hiring Manager at {job.company},\n\n"
            f"I am interested in the {job.title} position.\n\n{evidence_paragraph}\n\n"
            f"Thank you for considering my application.\n\nBest regards,\n{profile.name}",
            citations=citations,
        ),
        "resume_suggestions": ArtifactContent(suggestions=suggestions, citations=citations),
        "recruiter_message": ArtifactContent(
            text=f"Hello [Recruiter name],\n\n"
            f"I am interested in the {job.title} position at {job.company}.\n\n{evidence_paragraph}\n\n"
            f"Would you be available to discuss the role and its requirements?\n\n{profile.name}",
            citations=citations,
        ),
        "interview_brief": ArtifactContent(
            text=f"Interview preparation: {job.title} at {job.company}\n\n"
            + "\n".join(preparation)
            + "\n\nQuestions to clarify:\n- What are the role's day-to-day responsibilities?"
            + "\n- Which eligibility requirements need verification?\n- How will success be assessed?",
            citations=citations,
        ),
    }
    if model_drafts:
        specs["cover_letter"] = specs["cover_letter"].model_copy(
            update={"text": model_drafts["cover_letter"], "generation_method": "agents-sdk-v1"}
        )
        specs["resume_suggestions"] = specs["resume_suggestions"].model_copy(
            update={"suggestions": model_drafts["resume_suggestions"], "generation_method": "agents-sdk-v1"}
        )
        specs["recruiter_message"] = specs["recruiter_message"].model_copy(
            update={"text": model_drafts["recruiter_message"], "generation_method": "agents-sdk-v1"}
        )
        specs["interview_brief"] = specs["interview_brief"].model_copy(
            update={"text": model_drafts["interview_brief"], "generation_method": "agents-sdk-v1"}
        )
    return report, job, specs
