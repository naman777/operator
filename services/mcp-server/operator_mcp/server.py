"""Local stdio MCP server exposing bounded Operator operations."""

import os

from mcp.server import MCPServer

from .client import OperatorClient

mcp = MCPServer("Operator")


def client() -> OperatorClient:
    return OperatorClient(
        os.getenv("OPERATOR_API_URL", "http://127.0.0.1:8000"),
        os.getenv("OPERATOR_TOKEN", ""),
    )


@mcp.tool()
def create_mission(job_url: str, goal: str, budget_usd: float = 1.0) -> dict:
    """Create a draft opportunity mission in the configured workspace."""
    return client().create_mission(job_url, goal, budget_usd)


@mcp.tool()
def get_mission_status(mission_id: str) -> dict:
    """Read a mission's durable steps, status, and result."""
    return client().get_mission_status(mission_id)


@mcp.tool()
def list_pending_approvals() -> list[dict]:
    """List pending human approvals in the configured workspace."""
    return client().list_pending_approvals()


@mcp.tool()
def resolve_approval(approval_id: str, decision: str, note: str | None = None) -> dict:
    """Approve or reject one pending action; the API enforces workspace ownership."""
    return client().resolve_approval(approval_id, decision, note)


@mcp.tool()
def list_applications() -> list[dict]:
    """List the configured workspace's application pipeline."""
    return client().list_applications()


@mcp.tool()
def propose_action(mission_id: str, action_type: str, proposed_payload: dict) -> dict:
    """Propose a mock email draft or calendar event for human approval."""
    return client().propose_action(mission_id, action_type, proposed_payload)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
