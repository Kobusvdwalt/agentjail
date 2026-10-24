import asyncio
from dataclasses import dataclass

from pydantic import BaseModel


class LeaseConflict(Exception):
    pass


class LeaseGrant(BaseModel):
    lease_token: str
    lease_seconds: int


@dataclass
class ExecutionLease:
    token: str
    deadline: float
    timer: asyncio.Task[None] | None = None
