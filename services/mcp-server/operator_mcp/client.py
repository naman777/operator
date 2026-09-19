"""Authenticated API adapter used by MCP tools.

The bearer token is process configuration, never a model-visible tool argument.
"""

from uuid import uuid4

import httpx


class OperatorAPIError(RuntimeError):
    pass


class OperatorClient:
    def __init__(self, base_url: str, token: str, transport=None):
        if not token:
            raise ValueError("OPERATOR_TOKEN is required")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.transport = transport

    def _request(self, method: str, path: str, **kwargs):
        headers = {"Authorization": f"Bearer {self.token}"}
        headers.update(kwargs.pop("headers", {}))
        try:
            with httpx.Client(
                base_url=self.base_url,
                headers=headers,
                timeout=10,
                transport=self.transport,
            ) as client:
                response = client.request(method, path, **kwargs)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.json().get("detail", "Operator API request failed")
            raise OperatorAPIError(str(detail)) from exc
        except httpx.HTTPError as exc:
            raise OperatorAPIError("Operator API is unavailable") from exc

    def create_mission(self, job_url: str, goal: str, budget_usd: float = 1.0):
        return self._request(
            "POST",
            "/v1/missions",
            headers={"Idempotency-Key": str(uuid4())},
            json={"job_url": job_url, "goal": goal, "budget_usd": budget_usd},
        )

    def get_mission_status(self, mission_id: str):
        return self._request("GET", f"/v1/missions/{mission_id}/run")

    def list_pending_approvals(self):
        return self._request("GET", "/v1/approvals", params={"status": "pending"})

    def resolve_approval(self, approval_id: str, decision: str, note: str | None = None):
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        return self._request(
            "POST",
            f"/v1/approvals/{approval_id}/{decision}",
            json={"note": note},
        )

    def list_applications(self):
        return self._request("GET", "/v1/applications")
