"""Deterministic, versioned regression evaluation for opportunity matching."""

import json
import time
from pathlib import Path

from operator_worker.analysis import match, verify

from .schemas import CandidateProfile, JobPosting

EVALUATOR_VERSION = "deterministic-v1"
DATASET_VERSION = "opportunity-v1"


def load_dataset(root: Path, version: str = DATASET_VERSION) -> dict:
    if version != DATASET_VERSION:
        raise ValueError(f"Unknown evaluation dataset: {version}")
    return json.loads((root / "evals" / "datasets" / f"{version}.json").read_text(encoding="utf-8"))


def run(root: Path, version: str = DATASET_VERSION) -> tuple[dict, list[dict]]:
    dataset = load_dataset(root, version)
    demo = root / "data" / "demo"
    profile = CandidateProfile.model_validate_json((demo / dataset["profile"]).read_text(encoding="utf-8"))
    results = []
    total_requirements = 0
    correct_requirements = 0
    total_citations = 0
    supported_requirements = 0
    unsupported_positives = 0
    absolute_score_error = 0.0
    total_latency = 0.0

    for case in dataset["cases"]:
        job = JobPosting.model_validate_json((demo / case["job"]).read_text(encoding="utf-8"))
        started = time.perf_counter()
        output = match(job, profile)
        verify(job, output)
        latency_ms = (time.perf_counter() - started) * 1000
        expected = case["expected"]
        expected_statuses = expected["requirements"]
        actual = {item["requirement_id"]: item for item in output["matches"]}
        correct = sum(
            1 for requirement_id, status in expected_statuses.items()
            if actual.get(requirement_id, {}).get("status") == status
        )
        case_requirement_count = len(expected_statuses)
        positive = [item for item in output["matches"] if item["status"] in {"supported", "partial"}]
        cited = sum(1 for item in positive if item["evidence_ids"])
        unsupported = sum(1 for item in positive if not item["evidence_ids"])
        accuracy = correct / case_requirement_count
        coverage = cited / len(positive) if positive else 1.0
        score_error = abs(float(output["score"]) - float(expected["score"]))
        passed = accuracy == 1 and score_error < 0.001 and unsupported == 0
        results.append(
            {
                "case_id": case["id"],
                "job_title": job.title,
                "passed": passed,
                "expected_score": expected["score"],
                "actual_score": output["score"],
                "requirement_accuracy": accuracy,
                "citation_coverage": coverage,
                "unsupported_positive_count": unsupported,
                "latency_ms": round(latency_ms, 3),
            }
        )
        total_requirements += case_requirement_count
        correct_requirements += correct
        supported_requirements += len(positive)
        total_citations += cited
        unsupported_positives += unsupported
        absolute_score_error += score_error
        total_latency += latency_ms

    count = len(results)
    metrics = {
        "case_count": count,
        "requirement_accuracy": correct_requirements / total_requirements,
        "score_mae": absolute_score_error / count,
        "citation_coverage": total_citations / supported_requirements if supported_requirements else 1.0,
        "unsupported_positive_rate": (
            unsupported_positives / supported_requirements if supported_requirements else 0.0
        ),
        "mean_latency_ms": round(total_latency / count, 3),
    }
    return metrics, results


def compare(baseline: dict, candidate: dict) -> dict:
    higher_is_better = ("requirement_accuracy", "citation_coverage")
    lower_is_better = ("score_mae", "unsupported_positive_rate", "mean_latency_ms")
    deltas = {key: candidate[key] - baseline[key] for key in higher_is_better + lower_is_better}
    regression = any(deltas[key] < -1e-9 for key in higher_is_better) or any(
        deltas[key] > 1e-9 for key in ("score_mae", "unsupported_positive_rate")
    )
    return {"deltas": deltas, "regression": regression}
