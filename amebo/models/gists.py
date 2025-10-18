from datetime import datetime
from json import loads
from typing import Optional, Union

from pydantic import AnyHttpUrl
from pydantic import BaseModel as Model
from pydantic import Field, field_validator

from amebo.models.actions import Action


class Resubscriptions(Model):
    subscription: int
    timeline: datetime
