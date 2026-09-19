import httpx
import pytest

from operator_mcp.client import OperatorAPIError, OperatorClient


def test_token_is_header_only_and_mission_has_idempotency_key():
    seen = {}

    def handler(request):
        seen["request"] = request
        return httpx.Response(201, json={"id": "mission-1", "status": "draft"})

    client = OperatorClient("https://operator.test", "secret-token", httpx.MockTransport(handler))
    result = client.create_mission("https://example.com/job", "Assess this opportunity")
    request = seen["request"]
    assert result["id"] == "mission-1"
    assert request.headers["authorization"] == "Bearer secret-token"
    assert request.headers["idempotency-key"]
    assert b"secret-token" not in request.content


def test_safe_read_and_approval_routes():
    routes = []

    def handler(request):
        routes.append((request.method, request.url.path, request.url.query))
        if request.url.path.endswith("/run"):
            return httpx.Response(200, json={"mission": {"status": "awaiting_approval"}})
        if request.url.path == "/v1/approvals":
            return httpx.Response(200, json=[])
        if request.url.path == "/v1/applications":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"status": "approved"})

    client = OperatorClient("https://operator.test", "token", httpx.MockTransport(handler))
    client.get_mission_status("mission-1")
    client.list_pending_approvals()
    client.resolve_approval("approval-1", "approve", "Reviewed")
    client.list_applications()
    assert routes[0][1] == "/v1/missions/mission-1/run"
    assert routes[1][1] == "/v1/approvals" and b"status=pending" in routes[1][2]
    assert routes[2][1] == "/v1/approvals/approval-1/approve"
    assert routes[3][1] == "/v1/applications"


def test_invalid_decision_and_api_errors_are_safe():
    client = OperatorClient(
        "https://operator.test",
        "token",
        httpx.MockTransport(lambda request: httpx.Response(404, json={"detail": "Not found"})),
    )
    with pytest.raises(ValueError, match="approve or reject"):
        client.resolve_approval("approval-1", "send")
    with pytest.raises(OperatorAPIError, match="Not found"):
        client.get_mission_status("missing")
