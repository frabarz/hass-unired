"""Shared base entity for one Unired account instrument."""

from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import UniredCoordinator


class UniredEntity(CoordinatorEntity[UniredCoordinator]):
    """Base entity reading from the Unired coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: UniredCoordinator) -> None:
        """Bind the entity to its coordinator."""
        super().__init__(coordinator)
