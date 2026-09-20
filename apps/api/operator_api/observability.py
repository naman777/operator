"""Workspace-scoped operational metrics derived from durable product records."""

import math
from collections import defaultdict
from datetime import timedelta, timezone

from sqlalchemy import select

from .db import ExternalAction, Mission, MissionStep, ModelCall, StepOutput, utcnow


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * fraction) - 1)], 3)


def summary(db, workspace_id: str) -> dict:
    missions = list(
        db.scalars(
            select(Mission).where(Mission.workspace_id == workspace_id).order_by(Mission.created_at)
        )
    )
    mission_ids = [mission.id for mission in missions]
    counts = defaultdict(int)
    for mission in missions:
        counts[mission.status] += 1
    terminal_count = sum(counts[status] for status in ("completed", "failed", "cancelled"))

    steps = []
    model_calls = []
    if mission_ids:
        steps = list(
            db.execute(
                select(MissionStep, StepOutput)
                .outerjoin(StepOutput, StepOutput.step_id == MissionStep.id)
                .where(MissionStep.mission_id.in_(mission_ids))
            )
        )
        model_calls = list(
            db.scalars(select(ModelCall).where(ModelCall.mission_id.in_(mission_ids)))
        )

    step_groups = defaultdict(list)
    for step, output in steps:
        step_groups[step.name].append((step, output))
    step_metrics = []
    for name, rows in sorted(step_groups.items()):
        completed = sum(step.status == "completed" for step, _ in rows)
        failed = sum(step.status == "failed" for step, _ in rows)
        decided = completed + failed
        latencies = [float(output.latency_ms) for _, output in rows if output and output.latency_ms is not None]
        step_metrics.append(
            {
                "name": name,
                "attempted": len(rows),
                "completed": completed,
                "failed": failed,
                "success_rate": completed / decided if decided else None,
                "p50_latency_ms": _percentile(latencies, 0.50),
                "p95_latency_ms": _percentile(latencies, 0.95),
            }
        )

    tool_groups = defaultdict(list)
    for call in model_calls:
        tool_groups[f"model:{call.step}"].append(call.status == "completed")
    actions = list(
        db.scalars(select(ExternalAction).where(ExternalAction.workspace_id == workspace_id))
    )
    for action in actions:
        tool_groups[f"connector:{action.type}"].append(action.status == "created")
    tool_metrics = [
        {
            "name": name,
            "attempted": len(results),
            "succeeded": sum(results),
            "success_rate": sum(results) / len(results),
        }
        for name, results in sorted(tool_groups.items())
    ]

    today = utcnow().date()
    current_week = today - timedelta(days=today.weekday())
    week_starts = [current_week - timedelta(weeks=offset) for offset in reversed(range(8))]
    weekly = {week: defaultdict(int) for week in week_starts}
    for mission in missions:
        created = mission.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        week = created.date() - timedelta(days=created.weekday())
        if week in weekly:
            weekly[week][mission.status] += 1
            weekly[week]["created"] += 1
    weekly_trend = []
    for week in week_starts:
        item = weekly[week]
        decided = sum(item[status] for status in ("completed", "failed", "cancelled"))
        weekly_trend.append(
            {
                "week_start": week,
                "created": item["created"],
                "completed": item["completed"],
                "failed": item["failed"],
                "cancelled": item["cancelled"],
                "success_rate": item["completed"] / decided if decided else None,
            }
        )

    total_cost = sum(call.cost_usd for call in model_calls)
    completed_count = counts["completed"]
    return {
        "generated_at": utcnow(),
        "mission_count": len(missions),
        "completed_count": completed_count,
        "failed_count": counts["failed"],
        "cancelled_count": counts["cancelled"],
        "active_count": len(missions) - terminal_count - counts["draft"],
        "success_rate": completed_count / terminal_count if terminal_count else None,
        "total_model_cost_usd": round(total_cost, 8),
        "cost_per_completed_mission_usd": (
            round(total_cost / completed_count, 8) if completed_count else None
        ),
        "step_metrics": step_metrics,
        "tool_metrics": tool_metrics,
        "weekly_trend": weekly_trend,
    }
