"""Die Solar Manager Integration für Home Assistant.

Liest Daten vom Endpoint /v1/chart/gateway/{smId} der Solar Manager Cloud API
(https://cloud.solar-manager.ch/swagger.json) und stellt sie als Sensoren
(Leistung in W sowie zusätzlich Energie in kWh) zur Verfügung.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SolarManagerApiClient
from .const import (
    AUTH_METHOD_API_KEY,
    CONF_API_KEY,
    CONF_AUTH_METHOD,
    CONF_SCAN_INTERVAL,
    CONF_SM_ID,
    DATA_COORDINATOR,
    DATA_STATISTICS_COORDINATOR,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import (
    SolarManagerDataUpdateCoordinator,
    SolarManagerStatisticsCoordinator,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


def _build_client(hass: HomeAssistant, entry: ConfigEntry) -> SolarManagerApiClient:
    """Erstellt den API-Client passend zur gewählten Auth-Methode.

    Ältere Config-Entries (vor Einführung des API-Key-Supports) besitzen
    kein CONF_AUTH_METHOD-Feld und werden weiterhin als Benutzername/
    Passwort-Login behandelt.
    """
    session = async_get_clientsession(hass)
    auth_method = entry.data.get(CONF_AUTH_METHOD)

    if auth_method == AUTH_METHOD_API_KEY:
        return SolarManagerApiClient(
            sm_id=entry.data[CONF_SM_ID],
            session=session,
            api_key=entry.data[CONF_API_KEY],
        )

    return SolarManagerApiClient(
        sm_id=entry.data[CONF_SM_ID],
        session=session,
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Richtet einen Config-Entry (eine Solar Manager Anlage/smId) ein."""
    client = _build_client(hass, entry)

    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = SolarManagerDataUpdateCoordinator(hass, client, scan_interval)
    statistics_coordinator = SolarManagerStatisticsCoordinator(hass, client)

    await coordinator.async_config_entry_first_refresh()
    await statistics_coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_COORDINATOR: coordinator,
        DATA_STATISTICS_COORDINATOR: statistics_coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Entfernt einen Config-Entry wieder."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Wird aufgerufen, wenn die Optionen (z.B. Abfrageintervall) geändert werden."""
    await hass.config_entries.async_reload(entry.entry_id)
