from copy import deepcopy
import pytest
from operator_api.runtime import sample_job, sample_profile
from operator_worker.analysis import match, verify


def test_score_is_evidence_backed_and_location_separate():
    profile = sample_profile()
    northstar = sample_job("https://example.com/jobs/1")
    matched = match(northstar, profile)
    assert matched["score"] == 100
    assert matched["eligibility"] == "unknown"
    assert verify(northstar, matched)["requirements_checked"] == 2
    orbit = match(sample_job("https://example.com/jobs/3"), profile)
    assert orbit["score"] == 50
    assert orbit["eligibility"] == "ineligible"
    assert orbit["matches"][1]["evidence_ids"] == []


def test_unproven_skill_and_tampered_provenance_fail_closed():
    job = sample_job("https://example.com/jobs/1")
    profile = sample_profile()
    profile.evidence = []
    matched = match(job, profile)
    assert matched["score"] == 0
    assert all(m["status"] == "missing" for m in matched["matches"])
    forged = deepcopy(matched)
    forged["matches"][0]["status"] = "supported"
    with pytest.raises(ValueError, match="Unsupported positive"):
        verify(job, forged)
    forged = deepcopy(matched)
    forged["score"] = 100
    with pytest.raises(ValueError, match="reproduce"):
        verify(job, forged)
    job.requirements[0].source_id = "nonexistent"
    with pytest.raises(ValueError, match="Missing job source"):
        verify(job, matched)
