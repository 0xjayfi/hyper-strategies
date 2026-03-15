"""Base classes and data structures for the multi-angle content pipeline.

Defines the abstract ``ContentAngle`` interface that all angle detectors
implement, along with supporting dataclasses for screenshot configuration
and detection results.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


# ------------------------------------------------------------------
# Screenshot configuration
# ------------------------------------------------------------------


@dataclass
class PageCapture:
    """Describes a single page screenshot to capture."""

    route: str
    wait_selector: str
    capture_selector: str
    filename: str
    pre_capture_js: str | None = None


@dataclass
class ScreenshotConfig:
    """Collection of page captures needed for a content angle."""

    pages: list[PageCapture] = field(default_factory=list)


# ------------------------------------------------------------------
# Angle result
# ------------------------------------------------------------------


@dataclass
class AngleResult:
    """The output of a successful angle detection + payload build."""

    angle_type: str
    raw_score: float
    effective_score: float
    payload: dict
    screenshot_config: ScreenshotConfig
    prompt_path: str
    auto_publish: bool
    tone: str  # "analytical" or "neutral"


# ------------------------------------------------------------------
# Abstract base class
# ------------------------------------------------------------------


class ContentAngle(ABC):
    """Abstract base for all content angle detectors.

    Subclasses must set the class attributes and implement the three
    abstract methods.  The dispatcher calls ``detect()`` first; if the
    returned score is > 0 it proceeds to ``build_payload()`` and
    ``screenshot_config()``.
    """

    # -- class attributes (override in subclasses) --------------------
    angle_type: str = ""
    auto_publish: bool = False
    cooldown_days: int = 2
    tone: str = "analytical"

    # -- abstract methods ---------------------------------------------

    @abstractmethod
    def detect(self, datastore, nansen_client=None) -> float:
        """Return a raw post-worthiness score in [0, 1], or 0 if below threshold."""
        ...

    @abstractmethod
    def build_payload(self, datastore, nansen_client=None) -> dict:
        """Build the content payload JSON for the detected angle."""
        ...

    @abstractmethod
    def screenshot_config(self) -> ScreenshotConfig:
        """Return the screenshot configuration for this angle."""
        ...

    # -- concrete helpers ---------------------------------------------

    def load_payload(self, payload: dict) -> None:
        """Hydrate internal state from a saved payload dict.

        Override in subclasses whose ``screenshot_config`` depends on
        state set during ``detect``.  Called by the screenshot module
        so that a fresh angle instance can produce the correct config.
        """

    @property
    def prompt_path(self) -> str:
        """Return the path to the Markdown prompt template for this angle."""
        return f"src/content/prompts/{self.angle_type}.md"
