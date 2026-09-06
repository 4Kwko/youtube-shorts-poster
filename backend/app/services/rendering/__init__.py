"""Renderização vertical (9:16) dos clips."""

from __future__ import annotations

from app.services.rendering.errors import (
    RenderError,
    RenderFailedError,
    RenderSourceUnavailableError,
)
from app.services.rendering.filters import (
    DEFAULT_LAYOUT,
    LayoutPlan,
    VerticalLayout,
    build_background_filter,
    build_center_crop_filter,
    build_filtergraph,
    escape_filter_path,
    plan_layout,
)
from app.services.rendering.renderer import RenderResult, VerticalRenderer, build_render_args
from app.services.rendering.storage import RENDERS_SUBDIR, render_path

__all__ = [
    "DEFAULT_LAYOUT",
    "RENDERS_SUBDIR",
    "LayoutPlan",
    "RenderError",
    "RenderFailedError",
    "RenderResult",
    "RenderSourceUnavailableError",
    "VerticalLayout",
    "VerticalRenderer",
    "build_background_filter",
    "build_center_crop_filter",
    "build_filtergraph",
    "build_render_args",
    "escape_filter_path",
    "plan_layout",
    "render_path",
]
