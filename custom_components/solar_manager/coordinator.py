"""DataUpdateCoordinator für Solar Manager.

Es gibt zwei getrennte Coordinators:

- SolarManagerDataUpdateCoordinator: pollt /v1/chart/gateway/{smId}
  (Momentanleistungen), Standardintervall 30s.
- SolarManagerStatisticsCoordinator: pollt /v1/statistics/gateways/{smId}
  für den Zeitraum "seit Mitternacht bis jetzt" und liefert die von Solar
  Manager selbst berechneten Werte für Eigenverbrauch, Eigenverbrauchsrate
  und Autarkiegrad. Da sich diese Werte langsamer ändern, genügt ein
  selteneres Intervall (Standard 5 Minuten).
"""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    SolarManagerApiClient,
    SolarManagerApiError,
    SolarManagerAuthError,
)
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    STATISTICS_ACCURACY,
    STATISTICS_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class SolarManagerDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Holt periodisch die Gateway-Chart-Daten (Momentanleistungen) ab."""

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


class SolarManagerStatisticsCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Holt periodisch Autarkiegrad/Eigenverbrauch für den heutigen Tag ab.

    Fragt jeweils den Zeitraum von Mitternacht (lokale Zeit) bis jetzt ab,
    sodass die Werte "seit Tagesbeginn" repräsentieren - vergleichbar mit
    den "heute"-Werten in der Solar Manager App.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: SolarManagerApiClient,
        scan_interval: int = STATISTICS_SCAN_INTERVAL,
    ) -> None:
        self.client = client
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_statistics",
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        date_to = dt_util.utcnow()
        date_from = dt_util.as_utc(dt_util.start_of_local_day())

        try:
            return await self.client.async_get_gateway_statistics(
                accuracy=STATISTICS_ACCURACY,
                date_from=date_from,
                date_to=date_to,
            )
        except SolarManagerAuthError as err:
            raise UpdateFailed(f"Authentifizierung fehlgeschlagen: {err}") from err
        except SolarManagerApiError as err:
            raise UpdateFailed(
                f"Fehler beim Abrufen der Statistik-Daten: {err}"
            ) from err
