"""Evaluate supplied constraints only; never infer graduation or experience bounds from a title."""

from operator_api.schemas import CandidateProfile, EligibilityCheck, JobPosting


def evaluate(job: JobPosting, profile: CandidateProfile):
    rules = job.eligibility_requirements
    checks = []
    sources = {source.id for source in job.sources}
    complete = bool(
        rules and rules.requirements_complete and rules.source_ids and set(rules.source_ids) <= sources
    )

    def add(name, status, detail, candidate=None, required=None):
        checks.append(
            EligibilityCheck(
                check=name,
                status=status,
                detail=detail,
                candidate_value=None if candidate is None else str(candidate),
                required_value=None if required is None else str(required),
            )
        )

    def unspecified(name, category):
        absent = complete and not any(
            r.category == category and r.importance == "required" for r in job.requirements
        )
        add(
            name,
            "pass" if absent else "unknown",
            "No restriction in the reviewed requirements."
            if absent
            else "No explicit, structured requirement is available; manual review is needed.",
        )

    def bounds(name, value, lower, upper, category):
        if lower is None and upper is None:
            unspecified(name, category)
        elif value is None:
            add(name, "unknown", "Candidate information is missing.", required=f"{lower} to {upper}")
        else:
            passed = (lower is None or value >= lower) and (upper is None or value <= upper)
            add(
                name,
                "pass" if passed else "fail",
                "Compared with explicit inclusive bounds.",
                value,
                f"minimum {lower if lower is not None else 'unspecified'}, maximum {upper if upper is not None else 'unspecified'}",
            )

    if job.location and profile.locations:
        # A preference for remote work does not authorize relocation to an on-site role.
        passed = job.location.strip().casefold() in {value.strip().casefold() for value in profile.locations}
        add(
            "location",
            "pass" if passed else "fail",
            "Compared exact stated locations; remote is not a wildcard.",
            ", ".join(profile.locations),
            job.location,
        )
    elif job.location:
        add("location", "unknown", "Candidate locations are missing.", required=job.location)
    else:
        unspecified("location", "location")
    bounds(
        "graduation_year",
        profile.graduation_year,
        rules.graduation_year_min if rules else None,
        rules.graduation_year_max if rules else None,
        "education",
    )
    bounds(
        "experience_years",
        profile.experience_years,
        rules.experience_years_min if rules else None,
        rules.experience_years_max if rules else None,
        "experience",
    )
    accepted = rules.accepted_work_authorizations if rules else None
    if accepted:
        if not profile.work_authorization:
            add(
                "work_authorization",
                "unknown",
                "Candidate authorization is not documented.",
                required=", ".join(accepted),
            )
        else:
            matched = {value.strip().casefold() for value in accepted} & {
                value.strip().casefold() for value in profile.work_authorization
            }
            add(
                "work_authorization",
                "pass" if matched else "fail",
                "Compared exact authorization alternatives; no country equivalence was inferred.",
                ", ".join(profile.work_authorization),
                ", ".join(accepted),
            )
    else:
        unspecified("work_authorization", "authorization")
    if rules and (rules.internship_start or rules.internship_end):
        if (
            not rules.internship_start
            or not rules.internship_end
            or not profile.available_from
            or not profile.available_until
        ):
            add("internship_dates", "unknown", "Both role dates and candidate availability are needed.")
        else:
            passed = (
                profile.available_from <= rules.internship_start
                and profile.available_until >= rules.internship_end
            )
            add(
                "internship_dates",
                "pass" if passed else "fail",
                "Candidate must cover the full stated internship period.",
                f"{profile.available_from} to {profile.available_until}",
                f"{rules.internship_start} to {rules.internship_end}",
            )
    else:
        add(
            "internship_dates",
            "pass" if complete else "unknown",
            "No date restriction in reviewed requirements."
            if complete
            else "Internship dates have not been verified.",
        )
    add(
        "requirements_coverage",
        "pass" if complete else "unknown",
        "All hard requirements are marked reviewed with stored sources."
        if complete
        else "Hard-requirement coverage has not been confirmed; skill fit alone cannot establish eligibility.",
    )
    status = (
        "ineligible"
        if any(c.status == "fail" for c in checks)
        else "unknown"
        if any(c.status == "unknown" for c in checks)
        else "eligible"
    )
    return status, [check.model_dump(mode="json") for check in checks]
