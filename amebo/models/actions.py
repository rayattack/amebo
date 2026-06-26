from datetime import datetime
from json import loads
from typing import Optional, Union

from pydantic import AnyHttpUrl
from pydantic import BaseModel as Model
from pydantic import Field, field_validator


COMPATIBILITY_MODES = ('NONE', 'BACKWARD', 'FORWARD', 'FULL')
ACTION_STATUSES = ('active', 'deprecated', 'retired')


class Action(Model):
    action: str
    application: str
    schemata: Union[dict, str]
    # compatibility policy this action promises its successors; the predecessor's
    # policy is what governs whether a new version is allowed (Confluent-style).
    compatibility: Optional[str] = 'BACKWARD'
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

    @field_validator('compatibility')
    @classmethod
    def validate_compatibility(cls, value: Optional[str]):
        if value is None: return 'BACKWARD'
        upper = value.upper()
        if upper not in COMPATIBILITY_MODES:
            raise ValueError(f'compatibility must be one of {", ".join(COMPATIBILITY_MODES)}')
        return upper


class ActionTransition(Model):
    """PATCH body for an action's lifecycle. Both fields are optional; the handler
    requires at least one so a no-op PATCH is rejected."""
    status: Optional[str] = None
    successor: Optional[str] = None

    @field_validator('status')
    @classmethod
    def validate_status(cls, value: Optional[str]):
        if value is None: return value
        lower = value.lower()
        if lower not in ACTION_STATUSES:
            raise ValueError(f'status must be one of {", ".join(ACTION_STATUSES)}')
        return lower
