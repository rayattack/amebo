from datetime import datetime
from json import loads
from typing import Optional, Union

from pydantic import AnyHttpUrl
from pydantic import BaseModel as Model
from pydantic import Field, field_validator

from amebo.models.actions import Action


class Subscriber(Model):
    subscriber: Optional[int]
    action: str
    producer: str
    endpoint: str
    description: str
    timestamped: datetime = Field(default_factory=datetime.now)


class Gistings(Model):
    attempts: int = 0
    action: Action
    subscriber: Subscriber
    status: int
