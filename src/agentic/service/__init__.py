"""HTTP service: OpenAPI-documented orchestrator API + A2A endpoints per agent."""

from __future__ import annotations

from .app import create_app, serve

__all__ = ["create_app", "serve"]
