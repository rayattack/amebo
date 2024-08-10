from datetime import datetime
from json import loads
from typing import Optional, Union

from pydantic import AnyHttpUrl
from pydantic import BaseModel as Model
from pydantic import Field, field_validator

from amebo.models.actions import Action


class Subscriptions(Model):
    subscription: Optional[int]
    action: str
    application: str
    handler: str
    description: str
    timestamped: datetime = Field(default_factory=datetime.now)


class Gists(Model):
    attempts: int = 0
    action: Action
    subscription: Subscriptions
    status: int
