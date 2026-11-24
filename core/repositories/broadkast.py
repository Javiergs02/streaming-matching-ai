"""Abstract repository protocol for Broadkast content."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.domain.broadkast import BroadkastContent


@runtime_checkable
class BroadkastRepository(Protocol):
    """Interface for retrieving Broadkast content.

    The matching layer depends on this abstraction, not on any
    concrete implementation (CSV, PostgreSQL, etc.).
    """

    def get_contents(self) -> list[BroadkastContent]:
        """Return all Broadkast content items."""
        ...
