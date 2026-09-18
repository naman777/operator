from datetime import date
import pytest
from pydantic import ValidationError
from operator_api.runtime import sample_job, sample_profile
from operator_api.schemas import EligibilityRequirements
from operator_worker.analysis import match, verify
from operator_worker.eligibility import evaluate


def check(job, profile, name):
    return next(c for c in evaluate(job, profile)[1] if c["check"] == name)["status"]


def test_title_does_not_invent_graduation_constraint():
    job, profile = sample_job("https://example.com/jobs/1"), sample_profile()
    profile.graduation_year = 2020
    assert check(job, profile, "graduation_year") == "unknown"
    assert evaluate(job, profile)[0] == "unknown"


def test_remote_preference_does_not_pass_onsite_role():
    assert check(sample_job("https://example.com/jobs/3"), sample_profile(), "location") == "fail"


@pytest.mark.parametrize(
    "years,expected", [(None, "unknown"), (1, "fail"), (2, "pass"), (4, "pass"), (5, "fail")]
)
def test_explicit_experience_bounds(years, expected):
    job, profile = sample_job("https://example.com/jobs/1"), sample_profile()
    job.eligibility_requirements = EligibilityRequirements(experience_years_min=2, experience_years_max=4)
    profile.experience_years = years
    assert check(job, profile, "experience_years") == expected


def test_authorization_must_match_country_and_missing_information_stays_unknown():
    job, profile = sample_job("https://example.com/jobs/1"), sample_profile()
    job.eligibility_requirements = EligibilityRequirements(accepted_work_authorizations=["United Kingdom"])
    assert check(job, profile, "work_authorization") == "fail"
    profile.work_authorization = []
    assert check(job, profile, "work_authorization") == "unknown"
    profile.work_authorization = ["United Kingdom"]
    assert check(job, profile, "work_authorization") == "pass"


def test_all_explicit_requirements_with_provenance_and_dates():
    job, profile = sample_job("https://example.com/jobs/1"), sample_profile()
    job.eligibility_requirements = EligibilityRequirements(
        graduation_year_min=2026,
        graduation_year_max=2028,
        experience_years_min=0,
        accepted_work_authorizations=["India"],
        internship_start=date(2027, 6, 1),
        internship_end=date(2027, 8, 31),
        requirements_complete=True,
        source_ids=[job.sources[0].id],
    )
    profile.available_from, profile.available_until = date(2027, 5, 1), date(2027, 9, 1)
    assert evaluate(job, profile)[0] == "eligible"
    profile.available_until = date(2027, 8, 1)
    assert check(job, profile, "internship_dates") == "fail"
    profile.available_until = None
    assert check(job, profile, "internship_dates") == "unknown"
    job.eligibility_requirements.source_ids = ["missing"]
    assert check(job, profile, "requirements_coverage") == "unknown"


def test_invalid_ranges_and_tampered_explanations_are_rejected():
    with pytest.raises(ValidationError):
        EligibilityRequirements(experience_years_min=4, experience_years_max=1)
    job = sample_job("https://example.com/jobs/1")
    matched = match(job, sample_profile())
    matched["eligibility_checks"][0]["detail"] = "Unsupported claim"
    with pytest.raises(ValueError, match="reproduce"):
        verify(job, matched)
