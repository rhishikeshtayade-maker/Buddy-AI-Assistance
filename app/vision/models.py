"""BUDDY Computer Vision Models.

Provides models for bounding boxes, detected UI elements, and screen state representation.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional, Tuple
from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    """Rectangular screen region in pixel coordinates."""

    x: int = Field(..., ge=0, description="Top-left X coordinate")
    y: int = Field(..., ge=0, description="Top-left Y coordinate")
    width: int = Field(..., gt=0, description="Box width in pixels")
    height: int = Field(..., gt=0, description="Box height in pixels")

    model_config = {"frozen": True}

    @property
    def center(self) -> Tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    @property
    def as_tuple(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)


class VisionTarget(BaseModel):
    """Empirically located and verified UI element on screen."""

    target_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    label: str = Field(..., description="Descriptive label or visible text of UI element")
    bounding_box: BoundingBox = Field(..., description="Element screen coordinates")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Detection confidence score")
    screen_fingerprint: str = Field(..., description="Hash representing screen visual state at detection time")
    screen_dimensions: Tuple[int, int] = Field(default=(1920, 1080), description="Display width and height")
    timestamp: float = Field(default_factory=time.time, description="Detection timestamp")
    category: str = Field(default="SAFE", description="Policy risk category: SAFE, MODERATE, DANGEROUS, CRITICAL")
    is_verified: bool = Field(default=True, description="Whether target has been empirically verified")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional element properties")

    model_config = {"frozen": True}

    @property
    def center(self) -> Tuple[int, int]:
        return self.bounding_box.center
