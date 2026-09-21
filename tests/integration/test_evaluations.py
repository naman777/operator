from fastapi.testclient import TestClient

from operator_api import evaluations
from operator_api.main import create_app


def session(client):
    token = client.post("/v1/guest-sessions?demo=true").json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_evaluation_run_is_measured_and_persisted(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'eval.db'}")) as client:
        headers = session(client)
        response = client.post(
            "/v1/evals/runs",
            headers=headers,
            json={"dataset_version": "opportunity-v1"},
        )
        assert response.status_code == 201
        run = response.json()
        assert run["metrics"]["case_count"] == 3
        assert run["metrics"]["pass_rate"] == 1
        assert run["metrics"]["eligibility_accuracy"] == 1
        assert run["metrics"]["requirement_accuracy"] == 1
        assert run["metrics"]["score_mae"] == 0
        assert run["metrics"]["citation_coverage"] == 1
        assert run["metrics"]["unsupported_positive_rate"] == 0
        assert all(case["passed"] for case in run["case_results"])
        assert client.get(f"/v1/evals/runs/{run['id']}", headers=headers).json()["id"] == run["id"]
        assert [item["id"] for item in client.get("/v1/evals/runs", headers=headers).json()] == [
            run["id"]
        ]


def test_expanded_evaluation_covers_planned_forty_case_suite(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'expanded-eval.db'}")) as client:
        headers = session(client)
        response = client.post(
            "/v1/evals/runs",
            headers=headers,
            json={"dataset_version": "opportunity-v3"},
        )
        assert response.status_code == 201
        run = response.json()
        assert run["evaluator_version"] == "deterministic-v3"
        assert run["metrics"]["case_count"] == 40
        assert run["metrics"]["pass_rate"] == 1
        assert run["metrics"]["eligibility_accuracy"] == 1
        assert run["metrics"]["requirement_accuracy"] == 1
        assert run["metrics"]["unsupported_positive_rate"] == 0
        assert run["metrics"]["p50_latency_ms"] >= 0
        assert run["metrics"]["p95_latency_ms"] >= run["metrics"]["p50_latency_ms"]
        assert {case["category"] for case in run["case_results"]} >= {
            "matching",
            "weak-evidence",
            "partial-match",
            "scoring",
            "prompt-injection",
            "eligibility",
            "eligibility-ambiguity",
            "partial-extraction",
            "missing-location",
        }


def test_evaluation_runs_are_workspace_scoped_and_comparable(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'scope.db'}")) as client:
        first_headers = session(client)
        first = client.post("/v1/evals/runs", headers=first_headers, json={}).json()
        second = client.post("/v1/evals/runs", headers=first_headers, json={}).json()
        comparison = client.get(
            "/v1/evals/compare",
            headers=first_headers,
            params={"baseline": first["id"], "candidate": second["id"]},
        )
        assert comparison.status_code == 200
        assert comparison.json()["regression"] is False
        assert comparison.json()["deltas"]["requirement_accuracy"] == 0

        other_headers = session(client)
        assert client.get(f"/v1/evals/runs/{first['id']}", headers=other_headers).status_code == 404
        assert (
            client.get(
                "/v1/evals/compare",
                headers=other_headers,
                params={"baseline": first["id"], "candidate": second["id"]},
            ).status_code
            == 404
        )


def test_unknown_evaluation_dataset_is_rejected(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'invalid.db'}")) as client:
        headers = session(client)
        response = client.post(
            "/v1/evals/runs",
            headers=headers,
            json={"dataset_version": "future-v2"},
        )
        assert response.status_code == 422


def test_comparison_flags_eligibility_regression_and_accepts_legacy_metrics():
    baseline = {
        "requirement_accuracy": 1.0,
        "citation_coverage": 1.0,
        "score_mae": 0.0,
        "unsupported_positive_rate": 0.0,
        "mean_latency_ms": 1.0,
        "pass_rate": 1.0,
        "eligibility_accuracy": 1.0,
    }
    candidate = {**baseline, "pass_rate": 0.9, "eligibility_accuracy": 0.8}
    assert evaluations.compare(baseline, candidate)["regression"] is True

    legacy = {key: value for key, value in baseline.items() if key not in {"pass_rate", "eligibility_accuracy"}}
    assert evaluations.compare(legacy, legacy)["regression"] is False
