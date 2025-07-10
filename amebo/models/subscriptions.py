from datetime import datetime
from json import loads
from typing import Optional, Union

from pydantic import AnyHttpUrl
from pydantic import BaseModel as Model
from pydantic import Field, field_validator

from amebo.models.actions import Action


class Subscriptions(Model):
    subscription: Optional[int] = None
    application: str
    action: str
    handler: str
    secret: str
    max_retries: Optional[int] = Field(le=10_000, ge=1, default=3)
    timestamped: datetime = Field(default_factory=datetime.now)

    @field_validator('handler')
    @classmethod
    def _handler(cls, val: str):
        if not val.startswith('/'): raise ValueError('Subscription handlers must start with a leading `/`')
        return val


class Gists(Model):
    attempts: int = 0
    action: Action
    subscription: Subscriptions
    status: int
