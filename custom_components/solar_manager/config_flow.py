"""Config flow für die Solar Manager Integration.

Der Nutzer wählt zunächst die Authentifizierungsmethode:
- Benutzername + Passwort
- API-Key

In beiden Fällen ist die smId (Gateway-ID) ein Pflichtfeld.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    SolarManagerApiClient,
    SolarManagerApiError,
    SolarManagerAuthError,
    SolarManagerNotFoundError,
)
from .const import (
    AUTH_METHOD_API_KEY,
    AUTH_METHOD_PASSWORD,
    CONF_API_KEY,
    CONF_AUTH_METHOD,
    CONF_SCAN_INTERVAL,
    CONF_SM_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

STEP_PASSWORD_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_SM_ID): str,
    }
)

STEP_API_KEY_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): str,
        vol.Required(CONF_SM_ID): str,
    }
)


class SolarManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config Flow für Solar Manager."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Erster Schritt: Auswahl der Authentifizierungsmethode."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["password", "api_key"],
        )

    async def async_step_password(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Einrichtung mit Benutzername + Passwort."""
        errors: dict[str, str] = {}

        if user_input is not None:
            sm_id = user_input[CONF_SM_ID].strip()

            await self.async_set_unique_id(sm_id)
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            client = SolarManagerApiClient(
                sm_id=sm_id,
                session=session,
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
            )
            try:
                await client.async_validate()
            except SolarManagerAuthError:
                errors["base"] = "invalid_auth"
            except SolarManagerNotFoundError:
                errors["base"] = "sm_id_not_found"
            except SolarManagerApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unerwarteter Fehler im Config Flow")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"Solar Manager ({sm_id})",
                    data={
                        CONF_AUTH_METHOD: AUTH_METHOD_PASSWORD,
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_SM_ID: sm_id,
                    },
                )

        return self.async_show_form(
            step_id="password",
            data_schema=STEP_PASSWORD_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_api_key(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Einrichtung mit API-Key."""
        errors: dict[str, str] = {}

        if user_input is not None:
            sm_id = user_input[CONF_SM_ID].strip()
            api_key = user_input[CONF_API_KEY].strip()

            await self.async_set_unique_id(sm_id)
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            client = SolarManagerApiClient(
                sm_id=sm_id,
                session=session,
                api_key=api_key,
            )
            try:
                await client.async_validate()
            except SolarManagerAuthError:
                errors["base"] = "invalid_api_key"
            except SolarManagerNotFoundError:
                errors["base"] = "sm_id_not_found"
            except SolarManagerApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unerwarteter Fehler im Config Flow")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"Solar Manager ({sm_id})",
                    data={
                        CONF_AUTH_METHOD: AUTH_METHOD_API_KEY,
                        CONF_API_KEY: api_key,
                        CONF_SM_ID: sm_id,
                    },
                )

        return self.async_show_form(
            step_id="api_key",
            data_schema=STEP_API_KEY_DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> SolarManagerOptionsFlow:
        return SolarManagerOptionsFlow(config_entry)


class SolarManagerOptionsFlow(config_entries.OptionsFlow):
    """Erlaubt das nachträgliche Anpassen des Abfrageintervalls."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )

        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL)
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
