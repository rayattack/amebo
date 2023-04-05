from datetime import datetime
from typing import Optional, Union

from pydantic import BaseModel as Model, validator, Field, AnyHttpUrl


class Microservice(Model):
    microservice: str
    location: AnyHttpUrl
    passkey: str
    timestamped: datetime = Field(default_factory=datetime.now)

    @validator('microservice')
    def no_spaces(cls, val: str) -> str:
        if val.count(' '): raise ValueError('microservice name can not contain spaces')
        return val

    @property
    def password(self):
        return '...'

class Location(Model):
    location: AnyHttpUrl
    passkey: str

class Event(Model):
    event: str
    microservice: str
    schemata: dict
    timestamped: datetime = Field(default_factory=datetime.now)


class Action(Model):
    action: Optional[int]
    event: str
    deduper: str
    payload: dict
    timestamped: datetime = Field(default_factory=datetime.now)


class Subscriber(Model):
    subscriber: Optional[int]
    event: str
    microservice: str
    endpoint: str
    description: str
    timestamped: datetime = Field(default_factory=datetime.now)


class Amebo(Model):
    attempts: int = 0
    event: Event
    subscriber: Subscriber
    status: int
