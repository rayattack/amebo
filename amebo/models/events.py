from datetime import datetime
from json import loads
from typing import Optional, Union

from pydantic import AnyHttpUrl
from pydantic import BaseModel as Model
from pydantic import Field, field_validator


class Events(Model):
    action: str = Field(...)
    passphrase: str
    event: Optional[int] = None
    deduper: str
    payload: Union[str, dict]
    timestamped: datetime = Field(default_factory=datetime.now)

    @field_validator('payload')
    def validate_payload(cls, value: Union[str, dict]):
        if isinstance(value, dict): return value
        return loads(value)
    
    @field_validator('action')
    def _action(cls, value: str):
        if not value: raise ValueError('Action is a required field')
        return value
