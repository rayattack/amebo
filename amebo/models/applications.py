from curses.ascii import isalnum
from datetime import datetime
from enum import Enum
from json import loads
from typing import Optional, Union

from pydantic import AnyHttpUrl
from pydantic import BaseModel as Model
from pydantic import Field, field_validator


class Credential(Model):
    username: str
    password: str
    scheme: str


class Application(Model):
    application: str = Field(min_length=1)
    address: AnyHttpUrl
    secret: str = Field(min_length=16)
    timestamped: datetime = Field(default_factory=datetime.now)

    @classmethod
    @field_validator('application')
    def no_spaces(cls, val: str) -> str:
        if val.count(' '): raise ValueError('Application name can not contain spaces')
        if not val.isalnum(): raise ValueError('Application name can only contain alphabets and numbers')
        return val

    @property
    def password(self):
        return '***'


class Location(Model):
    location: AnyHttpUrl
    secret: str


class Token(Model):
    secret: str
    microservice: str
