"""DataUpdateCoordinator für Solar Manager."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    SolarManagerApiClient,
    SolarManagerApiError,
    SolarManagerAuthError,
)
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class SolarManagerDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Holt periodisch die Gateway-Chart-Daten von der Solar Manager Cloud."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: SolarManagerApiClient,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        self.client = client
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.async_get_gateway_chart()
        except SolarManagerAuthError as err:
            raise UpdateFailed(f"Authentifizierung fehlgeschlagen: {err}") from err
        except SolarManagerApiError as err:
            raise UpdateFailed(f"Fehler beim Abrufen der Daten: {err}") from err
