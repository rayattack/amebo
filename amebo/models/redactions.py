from datetime import datetime

from pydantic import BaseModel as Model
from pydantic import Field, field_validator


class Redaction(Model):
    action: str
    field_path: str
    timestamped: datetime = Field(default_factory=datetime.now)

    @field_validator('field_path')
    @classmethod
    def _field_path(cls, val: str):
        if not val or not val.strip():
            raise ValueError('field_path cannot be empty')
        return val.strip()
