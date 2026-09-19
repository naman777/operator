from operator_api.runtime import sample_job, sample_profile
from operator_worker.analysis import match, verify
from operator_worker import model_runtime


def enable(monkeypatch):
    monkeypatch.setenv("OPERATOR_MODEL_ENABLED", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPERATOR_MODEL", "test-model")


def test_model_path_is_disabled_without_explicit_configuration(monkeypatch):
    monkeypatch.delenv("OPERATOR_MODEL_ENABLED", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPERATOR_MODEL", raising=False)
    job, profile = sample_job("https://example.com/jobs/1"), sample_profile()
    deterministic = match(job, profile)

    assert model_runtime.enrich_matches(job, profile, deterministic, 1.0) is deterministic
    assert model_runtime.generate_drafts(job, profile, deterministic, 1.0) is None


def test_semantic_explanations_cannot_change_verified_evidence(monkeypatch):
    enable(monkeypatch)
    job, profile = sample_job("https://example.com/jobs/1"), sample_profile()
    deterministic = match(job, profile)

    def valid_review(*_args):
        return model_runtime.SemanticMatchOutput(
            matches=[
                {
                    "requirement_id": item["requirement_id"],
                    "status": item["status"],
                    "evidence_ids": item["evidence_ids"],
                    "explanation": f"Reviewed evidence for {item['requirement_id']}.",
                }
                for item in deterministic["matches"]
            ]
        )

    monkeypatch.setattr(model_runtime, "_invoke", valid_review)
    enriched = model_runtime.enrich_matches(job, profile, deterministic, 1.0)
    assert enriched["matching_method"] == "agents-sdk-v1"
    assert verify(job, enriched)["verified"] is True

    def forged_review(*_args):
        proposed = [
            {
                "requirement_id": item["requirement_id"],
                "status": item["status"],
                "evidence_ids": item["evidence_ids"],
                "explanation": item["explanation"],
            }
            for item in deterministic["matches"]
        ]
        proposed[0]["evidence_ids"] = ["made-up"]
        return model_runtime.SemanticMatchOutput(matches=proposed)

    monkeypatch.setattr(model_runtime, "_invoke", forged_review)
    rejected = model_runtime.enrich_matches(job, profile, deterministic, 1.0)
    assert rejected["matches"] == deterministic["matches"]
    assert rejected["model_calls"] == 1
    assert rejected["model_fallback"] is True


def test_model_drafts_require_real_citations_and_source_backed_numbers(monkeypatch):
    enable(monkeypatch)
    job, profile = sample_job("https://example.com/jobs/1"), sample_profile()
    matched = match(job, profile)
    evidence_id = matched["matches"][0]["evidence_ids"][0]

    def drafts(*_args):
        return model_runtime.DraftOutput(
            cover_letter=f"I can discuss the documented work [{evidence_id}].",
            resume_suggestions=[f"Highlight the documented project [{evidence_id}]."],
            recruiter_message=f"I am interested in the role [{evidence_id}].",
            interview_brief=f"Prepare the documented example [{evidence_id}].",
        )

    monkeypatch.setattr(model_runtime, "_invoke", drafts)
    assert model_runtime.generate_drafts(job, profile, matched, 1.0)["cover_letter"]

    def invented_metric(*_args):
        output = drafts()
        output.cover_letter = f"Improved conversion by 98765% [{evidence_id}]."
        return output

    monkeypatch.setattr(model_runtime, "_invoke", invented_metric)
    assert model_runtime.generate_drafts(job, profile, matched, 1.0) is None
