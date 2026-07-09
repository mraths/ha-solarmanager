"""API client for the Solar Manager Cloud API.

Kommuniziert mit dem öffentlichen Endpoint
GET /v1/chart/gateway/{smId}

Unterstützt zwei Authentifizierungsarten, wie im Swagger unter
"securityDefinitions" definiert (https://cloud.solar-manager.ch/swagger.json):

1. Benutzername / Passwort -> HTTP Basic Auth ("basic")
2. API-Key -> wird wie ein Refresh-Token behandelt und über
   POST /v3/auth/refresh gegen ein kurzlebiges Bearer-Access-Token
   (Standard: 1h gültig) getauscht. Dies ist die von Solar Manager
   empfohlene, sicherere Variante (siehe Beschreibung von /v3/auth/refresh
   im Swagger: "For best security, treat your API Key as a refresh
   token — don't include it in every request.").
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

import aiohttp

from .const import (
    API_BASE_URL,
    API_ENDPOINT_AUTH_REFRESH,
    API_ENDPOINT_CHART_GATEWAY,
    API_ENDPOINT_STATISTICS_GATEWAY,
    TOKEN_EXPIRY_BUFFER_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15


def _format_api_datetime(dt: datetime) -> str:
    """Formatiert ein Datum wie von der API erwartet: 2022-01-11T00:00:00.000Z."""
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt_utc.microsecond // 1000:03d}Z"


class SolarManagerApiError(Exception):
    """Allgemeiner Fehler bei der Kommunikation mit der API."""


class SolarManagerAuthError(SolarManagerApiError):
    """Fehler bei der Authentifizierung (falsche Zugangsdaten / API-Key)."""


class SolarManagerNotFoundError(SolarManagerApiError):
    """Die angegebene smId wurde nicht gefunden."""


class SolarManagerApiClient:
    """Asynchroner Client für die Solar Manager Cloud API.

    Unterstützt wahlweise Benutzername/Passwort (Basic Auth) oder einen
    API-Key (wird intern gegen ein Bearer-Access-Token getauscht).
    Es muss entweder `username`+`password` ODER `api_key` übergeben werden.
    """

    def __init__(
        self,
        sm_id: str,
        session: aiohttp.ClientSession,
        username: str | None = None,
        password: str | None = None,
        api_key: str | None = None,
    ) -> None:
        if not api_key and not (username and password):
            raise ValueError(
                "Es muss entweder ein api_key oder username+password angegeben werden"
            )

        self._sm_id = sm_id
        self._session = session

        self._basic_auth: aiohttp.BasicAuth | None = None
        if username and password:
            self._basic_auth = aiohttp.BasicAuth(login=username, password=password)

        self._api_key = api_key
        self._access_token: str | None = None
        self._token_expires_at: datetime | None = None
        self._token_lock = asyncio.Lock()

    @property
    def uses_api_key(self) -> bool:
        """True, wenn diese Instanz per API-Key authentifiziert."""
        return self._api_key is not None

    async def async_get_gateway_chart(self) -> dict[str, Any]:
        """Ruft GET /v1/chart/gateway/{smId} ab.

        Antwort (GatewayChartDataSchema) enthält u.a.:
        - lastUpdate: Zeitstempel der letzten Aktualisierung
        - production: aktuelle Produktion in W
        - consumption: aktueller Verbrauch in W
        - battery: {capacity, batteryCharging, batteryDischarging}
        - arrows: Liste von Energieflüssen (z.B. fromPVToGrid) in W
        """
        url = f"{API_BASE_URL}{API_ENDPOINT_CHART_GATEWAY.format(sm_id=self._sm_id)}"
        return await self._async_request("GET", url)

    async def async_get_gateway_statistics(
        self, accuracy: str, date_from: datetime, date_to: datetime
    ) -> dict[str, Any]:
        """Ruft GET /v1/statistics/gateways/{smId} ab.

        Antwort (StatisticsOfGatewayResponseSchema) enthält für den
        angefragten Zeitraum (from -> to):
        - consumption: Verbrauch in Wh
        - production: Produktion in Wh
        - selfConsumption: Eigenverbrauch in Wh
        - selfConsumptionRate: Eigenverbrauchsrate in %
        - autarchyDegree: Autarkiegrad in %
        """
        url = (
            f"{API_BASE_URL}"
            f"{API_ENDPOINT_STATISTICS_GATEWAY.format(sm_id=self._sm_id)}"
        )
        params = {
            "accuracy": accuracy,
            "from": _format_api_datetime(date_from),
            "to": _format_api_datetime(date_to),
        }
        return await self._async_request("GET", url, params=params)

    async def async_validate(self) -> None:
        """Prüft die Zugangsdaten/den API-Key, wirft bei Fehlern eine Exception."""
        await self.async_get_gateway_chart()

    async def _async_request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        retry_on_auth_error: bool = True,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        auth: aiohttp.BasicAuth | None = None

        if self._api_key:
            token = await self._async_get_valid_access_token()
            headers["Authorization"] = f"Bearer {token}"
        else:
            auth = self._basic_auth

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.request(
                    method, url, headers=headers, auth=auth, params=params
                ) as response:
                    if response.status == 401:
                        # Bei API-Key: Access-Token evtl. abgelaufen/ungültig
                        # geworden -> einmal neu holen und erneut versuchen.
                        if self._api_key and retry_on_auth_error:
                            _LOGGER.debug(
                                "401 erhalten, erzwinge Token-Refresh und wiederhole"
                            )
                            self._access_token = None
                            self._token_expires_at = None
                            return await self._async_request(
                                method,
                                url,
                                params=params,
                                retry_on_auth_error=False,
                            )
                        raise SolarManagerAuthError(
                            "Ungültiger Benutzername/Passwort oder API-Key"
                        )
                    if response.status == 404:
                        raise SolarManagerNotFoundError(
                            f"smId '{self._sm_id}' wurde nicht gefunden"
                        )
                    response.raise_for_status()
                    return await response.json()
        except asyncio.TimeoutError as err:
            raise SolarManagerApiError(
                "Zeitüberschreitung bei der Kommunikation mit der Solar Manager API"
            ) from err
        except aiohttp.ClientError as err:
            raise SolarManagerApiError(
                f"Fehler bei der Kommunikation mit der Solar Manager API: {err}"
            ) from err

    async def _async_get_valid_access_token(self) -> str:
        """Gibt ein gültiges Access-Token zurück, holt bei Bedarf ein neues."""
        async with self._token_lock:
            now = datetime.now(timezone.utc)
            if (
                self._access_token is None
                or self._token_expires_at is None
                or now >= self._token_expires_at
            ):
                await self._async_refresh_access_token()
            return self._access_token  # type: ignore[return-value]

    async def _async_refresh_access_token(self) -> None:
        """Tauscht den API-Key (als refresh_token) gegen ein Access-Token.

        POST /v3/auth/refresh
        Body: {"grant_type": "refresh_token", "refresh_token": "<api_key>"}
        Antwort: {"access_token", "refresh_token", "expires_in", "token_type", "scope"}
        """
        url = f"{API_BASE_URL}{API_ENDPOINT_AUTH_REFRESH}"
        payload = {"grant_type": "refresh_token", "refresh_token": self._api_key}

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.post(url, json=payload) as response:
                    if response.status in (401, 400, 403):
                        raise SolarManagerAuthError(
                            "API-Key ist ungültig oder abgelaufen"
                        )
                    response.raise_for_status()
                    data = await response.json()
        except asyncio.TimeoutError as err:
            raise SolarManagerApiError(
                "Zeitüberschreitung beim Abrufen des Access-Tokens"
            ) from err
        except aiohttp.ClientError as err:
            raise SolarManagerApiError(
                f"Fehler beim Abrufen des Access-Tokens: {err}"
            ) from err

        access_token = data.get("access_token")
        expires_in = data.get("expires_in", 3600)
        if not access_token:
            raise SolarManagerAuthError(
                "Antwort von /v3/auth/refresh enthielt kein access_token"
            )

        self._access_token = access_token
        self._token_expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=max(expires_in - TOKEN_EXPIRY_BUFFER_SECONDS, 30)
        )
        _LOGGER.debug(
            "Neues Access-Token erhalten, gültig bis %s", self._token_expires_at
        )
