from datetime import datetime
from json import loads
from typing import Optional, Union

from pydantic import AnyHttpUrl
from pydantic import BaseModel as Model
from pydantic import Field, field_validator


class Credential(Model):
    username: str
    password: str
    scheme: str


class Microservice(Model):
    microservice: str
    address: AnyHttpUrl
    passkey: str = Field(min_length=32)
    timestamped: datetime = Field(default_factory=datetime.now)

    @classmethod
    @field_validator('microservice')
    def no_spaces(cls, val: str) -> str:
        if val.count(' '): raise ValueError('microservice name can not contain spaces')
        return val

    @property
    def password(self):
        return '***'


class Location(Model):
    location: AnyHttpUrl
    passkey: str
