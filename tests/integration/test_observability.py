from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from operator_api.db import Approval, ExternalAction, Mission, MissionStep, ModelCall, StepOutput, database
from operator_api.main import create_app


def test_observability_is_measured_and_workspace_scoped(tmp_path):
    url = f"sqlite:///{tmp_path / 'observability.db'}"
    with TestClient(create_app(url)) as client:
        guest = client.post("/v1/guest-sessions?demo=true").json()
        headers = {"Authorization": f"Bearer {guest['token']}"}
        other = client.post("/v1/guest-sessions?demo=true").json()
        other_headers = {"Authorization": f"Bearer {other['token']}"}

        first = client.post(
            "/v1/missions",
            headers={**headers, "Idempotency-Key": "observability-one"},
            json={"job_url": "https://example.com/jobs/1"},
        ).json()
        second = client.post(
            "/v1/missions",
            headers={**headers, "Idempotency-Key": "observability-two"},
            json={"job_url": "https://example.com/jobs/2"},
        ).json()

        engine, sessions = database(url)
        with sessions.begin() as db:
            db.get(Mission, first["id"]).status = "completed"
            db.get(Mission, second["id"]).status = "failed"
            completed_step = MissionStep(
                id=str(uuid4()), mission_id=first["id"], name="matching", status="completed", attempt=1
            )
            failed_step = MissionStep(
                id=str(uuid4()), mission_id=second["id"], name="matching", status="failed", attempt=2
            )
            db.add_all([completed_step, failed_step])
            db.flush()
            approval_id = str(uuid4())
            db.add(
                Approval(
                    id=approval_id,
                    mission_id=first["id"],
                    workspace_id=guest["workspace"]["id"],
                    action_type="email_draft",
                    proposed_payload={},
                    status="approved",
                )
            )
            db.flush()
            db.add_all(
                [
                    StepOutput(step_id=completed_step.id, latency_ms=20),
                    StepOutput(step_id=failed_step.id, latency_ms=80, error="sanitized"),
                    ModelCall(
                        id=str(uuid4()),
                        mission_id=first["id"],
                        step="matching",
                        model="test-model",
                        input_tokens=10,
                        output_tokens=5,
                        cost_usd=0.25,
                        status="completed",
                    ),
                    ModelCall(
                        id=str(uuid4()),
                        mission_id=second["id"],
                        step="matching",
                        model="test-model",
                        input_tokens=2,
                        output_tokens=0,
                        cost_usd=0.05,
                        status="failed",
                    ),
                    ExternalAction(
                        id=str(uuid4()),
                        workspace_id=guest["workspace"]["id"],
                        mission_id=first["id"],
                        approval_id=approval_id,
                        type="email_draft",
                        payload={},
                        provider="mock",
                        status="created",
                    ),
                ]
            )
        engine.dispose()

        response = client.get("/v1/observability/summary", headers=headers)
        assert response.status_code == 200
        metrics = response.json()
        assert metrics["mission_count"] == 2
        assert metrics["completed_count"] == 1
        assert metrics["failed_count"] == 1
        assert metrics["success_rate"] == 0.5
        assert metrics["total_model_cost_usd"] == 0.3
        assert metrics["cost_per_completed_mission_usd"] == 0.3
        assert metrics["step_metrics"] == [
            {
                "schema_version": "1.0",
                "name": "matching",
                "attempted": 2,
                "completed": 1,
                "failed": 1,
                "success_rate": 0.5,
                "p50_latency_ms": 20.0,
                "p95_latency_ms": 80.0,
            }
        ]
        assert {item["name"]: item["success_rate"] for item in metrics["tool_metrics"]} == {
            "connector:email_draft": 1.0,
            "model:matching": 0.5,
        }
        assert sum(item["created"] for item in metrics["weekly_trend"]) == 2

        other_metrics = client.get("/v1/observability/summary", headers=other_headers).json()
        assert other_metrics["mission_count"] == 0
        assert other_metrics["step_metrics"] == []
        assert other_metrics["tool_metrics"] == []

        with sessions() as db:
            assert len(db.scalars(select(Mission)).all()) == 2
        engine.dispose()
