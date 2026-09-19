"""Validation for local mock connector proposals; no external calls occur."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmailDraft(Payload):
    to: str = Field(min_length=3, max_length=320)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)

    @field_validator("to")
    @classmethod
    def valid_email(cls, value):
        if value.count("@") != 1 or "." not in value.rsplit("@", 1)[1]:
            raise ValueError("A valid recipient email is required")
        return value


class CalendarEvent(Payload):
    title: str = Field(min_length=1, max_length=200)
    starts_at: datetime
    ends_at: datetime
    attendee: str | None = Field(default=None, max_length=320)
    notes: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def valid_window(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("Calendar event must end after it starts")
        return self

    @field_validator("attendee")
    @classmethod
    def valid_attendee(cls, value):
        if value is not None and (value.count("@") != 1 or "." not in value.rsplit("@", 1)[1]):
            raise ValueError("Attendee must be a valid email")
        return value


MODELS = {"email_draft": EmailDraft, "calendar_event": CalendarEvent}
RISK = {"email_draft": "low", "calendar_event": "medium"}


def validate(action_type: str, payload: dict) -> dict:
    model = MODELS.get(action_type)
    if not model:
        raise ValueError("Unsupported connector action")
    return model.model_validate(payload).model_dump(mode="json")
