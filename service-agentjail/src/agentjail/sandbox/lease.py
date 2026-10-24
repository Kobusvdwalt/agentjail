import asyncio
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel


class LeaseConflict(Exception):
    pass


class LeaseGrant(BaseModel):
    lease_token: str
    lease_seconds: int
    expires_at: datetime


@dataclass
class ExecutionLease:
    token: str
    deadline: float
    not_after: datetime | None = None
    timer: asyncio.Task[None] | None = None
