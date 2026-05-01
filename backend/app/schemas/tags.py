"""Pydantic v2 schemas for Tag management."""

import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints


class TagScope(str, Enum):
    global_scope = "global"
    resource_type = "resource_type"


class TagValueRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    tag_definition_id: uuid.UUID
    value: str
    created_at: datetime


class TagDefinitionCreate(BaseModel):
    key: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    scope: TagScope
    resource_type: str | None = Field(default=None, max_length=100)
    description: str | None = None
    allowed_values: list[str] = Field(default_factory=list)


class TagDefinitionUpdate(BaseModel):
    description: str | None = None
    add_values: list[str] = Field(default_factory=list)
    remove_values: list[str] = Field(default_factory=list)


class TagDefinitionRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    key: str
    scope: TagScope
    resource_type: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime
    allowed_values: list[TagValueRead] = Field(default_factory=list)
