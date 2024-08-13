from datetime import datetime
from json import loads
from typing import Optional, Union

from pydantic import AnyHttpUrl
from pydantic import BaseModel as Model
from pydantic import Field, field_validator


class Action(Model):
    action: str
    application: str
    schemata: Union[dict, str]
    secret: str
    timestamped: datetime = Field(default_factory=datetime.now)

    @classmethod
    @field_validator('action')
    def validate_action(cls, value: str):
        if len(value) < 3: raise ValueError()
        return value

    @classmethod
    @field_validator('schemata')
    def validate_schemata(cls, value: Union[str, dict]):
        if isinstance(value, dict): return value
        return loads(value)
