"""Replay committed database events; Redis fan-out can later replace the polling wake-up."""

import asyncio
from sqlalchemy import select
from .db import Event, Mission
from .runtime import TERMINAL
from .schemas import EventView


def snapshot(sessions, mission_id, after):
    with sessions() as db:
        mission = db.get(Mission, mission_id)
        events = db.scalars(
            select(Event)
            .where(Event.mission_id == mission_id, Event.sequence > after)
            .order_by(Event.sequence)
            .limit(100)
        ).all()
        return [EventView.model_validate(event, from_attributes=True) for event in events], mission.status


async def stream(sessions, request, mission_id, after):
    yield ": connected\n\n"
    idle = 0
    while not await request.is_disconnected():
        events, status = await asyncio.to_thread(snapshot, sessions, mission_id, after)
        for event in events:
            yield f"id: {event.sequence}\nevent: mission\ndata: {event.model_dump_json()}\n\n"
            after = event.sequence
        if len(events) == 100:
            continue
        if status in TERMINAL:
            yield "event: end\ndata: {}\n\n"
            return
        idle += 1
        if idle % 20 == 0:
            yield ": heartbeat\n\n"
        await asyncio.sleep(0.5)
