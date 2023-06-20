from datetime import datetime
from json import loads
from typing import Optional, Union

from pydantic import AnyHttpUrl
from pydantic import BaseModel as Model
from pydantic import Field, validator


class Microservice(Model):
    microservice: str
    location: AnyHttpUrl
    passkey: str = Field(min_length=32)
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


class Action(Model):
    action: str
    microservice: str
    schemata: Union[dict, str]
    timestamped: datetime = Field(default_factory=datetime.now)

    @validator('action')
    def validate_action(cls, value: str):
        if len(value) < 3: raise ValueError()
        return value

    @validator('schemata')
    def validate_schemata(cls, value: Union[str, dict]):
        if isinstance(value, dict): return value
        return loads(value)


class Event(Model):
    event: Optional[int]
    action: str  # references acttions
    deduper: str
    payload: Union[str, dict]
    timestamped: datetime = Field(default_factory=datetime.now)

    @validator('payload')
    def validate_payload(cls, value: Union[str, dict]):
        if isinstance(value, dict): return value
        return loads(value)


class Subscriber(Model):
    subscriber: Optional[int]
    action: str
    microservice: str
    endpoint: str
    description: str
    timestamped: datetime = Field(default_factory=datetime.now)


class Gistings(Model):
    attempts: int = 0
    action: Action
    subscriber: Subscriber
    status: int


class Credential(Model):
    username: str
    password: str
    scheme: str
