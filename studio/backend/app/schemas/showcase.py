"""
Mark II Studio — Showcase Schemas
"""
from __future__ import annotations

import uuid
from typing import List, Optional
from pydantic import BaseModel, Field


class DemoStep(BaseModel):
    action: str
    target: str
    value: Optional[str] = None
    caption: str
    delay: int = 2000


class ShowcaseResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    title: str
    marketing_pitch: str
    hero_image_url: Optional[str] = None
    demo_script_json: List[DemoStep] = Field(default_factory=list)
    telemetry_highlights_json: dict = Field(default_factory=dict)
    is_public: bool
    view_count: int

    class Config:
        from_attributes = True
