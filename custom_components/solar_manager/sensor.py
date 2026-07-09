"""Sensor-Plattform für Solar Manager.

Stellt pro Gateway (smId) folgende Sensoren bereit:

Momentanleistung (aus /v1/chart/gateway/{smId}):
- Produktion (W)
- Verbrauch (W)
- Batterieladung (W)
- Batterieentladung (W)
- Batteriekapazität (%)

Zusätzlich berechnete Energiewerte (kWh):
Die API liefert nur Momentanleistungen (W), keine Energie (kWh/Wh).
Diese Integration berechnet daher lokal per Trapezregel (Leistung x Zeit)
laufende Energiezähler, die auch einen Neustart von Home Assistant
überstehen (RestoreEntity):
- Produktion (kWh)
- Verbrauch (kWh)
- Batterieladung (kWh)
- Batterieentladung (kWh)

Statistik-Werte "seit Mitternacht" (aus /v1/statistics/gateways/{smId}):
Diese Werte werden direkt von Solar Manager berechnet und periodisch
(Standard alle 5 Minuten) abgefragt:
- Eigenverbrauch (kWh)
- Eigenverbrauchsrate (%)
- Autarkiegrad (%)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_SM_ID,
    DATA_COORDINATOR,
    DATA_STATISTICS_COORDINATOR,
    DOMAIN,
    KEY_AUTARCHY_DEGREE,
    KEY_BATTERY,
    KEY_BATTERY_CAPACITY,
    KEY_BATTERY_CHARGING,
    KEY_BATTERY_DISCHARGING,
    KEY_CONSUMPTION,
    KEY_LAST_UPDATE,
    KEY_PRODUCTION,
    KEY_SELF_CONSUMPTION,
    KEY_SELF_CONSUMPTION_RATE,
    MANUFACTURER,
    MODEL,
)
from .coordinator import (
    SolarManagerDataUpdateCoordinator,
    SolarManagerStatisticsCoordinator,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class SolarManagerPowerSensorDescription(SensorEntityDescription):
    """Beschreibung eines Momentanleistungs-Sensors."""

    value_fn: Callable[[dict[str, Any]], float | None] = lambda data: None


POWER_SENSOR_DESCRIPTIONS: tuple[SolarManagerPowerSensorDescription, ...] = (
    SolarManagerPowerSensorDescription(
        key="production_power",
        translation_key="production_power",
        name="Solarstrom",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get(KEY_PRODUCTION),
    ),
    SolarManagerPowerSensorDescription(
        key="consumption_power",
        translation_key="consumption_power",
        name="Stromverbrauch",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get(KEY_CONSUMPTION),
    ),
    SolarManagerPowerSensorDescription(
        key="battery_charging_power",
        translation_key="battery_charging_power",
        name="Batterie Ladeleistung",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: (data.get(KEY_BATTERY) or {}).get(
            KEY_BATTERY_CHARGING
        ),
    ),
    SolarManagerPowerSensorDescription(
        key="battery_discharging_power",
        translation_key="battery_discharging_power",
        name="Batterie Entladeleistung",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: (data.get(KEY_BATTERY) or {}).get(
            KEY_BATTERY_DISCHARGING
        ),
    ),
    SolarManagerPowerSensorDescription(
        key="battery_capacity",
        translation_key="battery_capacity",
        name="Batteriekapazität",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: (data.get(KEY_BATTERY) or {}).get(
            KEY_BATTERY_CAPACITY
        ),
    ),
)


@dataclass(frozen=True, kw_only=True)
class SolarManagerEnergySensorDescription(SensorEntityDescription):
    """Beschreibung eines berechneten kWh-Energiesensors."""

    power_value_fn: Callable[[dict[str, Any]], float | None] = lambda data: None


ENERGY_SENSOR_DESCRIPTIONS: tuple[SolarManagerEnergySensorDescription, ...] = (
    SolarManagerEnergySensorDescription(
        key="production_energy",
        translation_key="production_energy",
        name="Produktion",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        power_value_fn=lambda data: data.get(KEY_PRODUCTION),
    ),
    SolarManagerEnergySensorDescription(
        key="consumption_energy",
        translation_key="consumption_energy",
        name="Verbrauch",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        power_value_fn=lambda data: data.get(KEY_CONSUMPTION),
    ),
    SolarManagerEnergySensorDescription(
        key="battery_charging_energy",
        translation_key="battery_charging_energy",
        name="Batterie Ladeenergie",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        power_value_fn=lambda data: (data.get(KEY_BATTERY) or {}).get(
            KEY_BATTERY_CHARGING
        ),
    ),
    SolarManagerEnergySensorDescription(
        key="battery_discharging_energy",
        translation_key="battery_discharging_energy",
        name="Batterie Entladeenergie",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        power_value_fn=lambda data: (data.get(KEY_BATTERY) or {}).get(
            KEY_BATTERY_DISCHARGING
        ),
    ),
)


@dataclass(frozen=True, kw_only=True)
class SolarManagerStatisticsSensorDescription(SensorEntityDescription):
    """Beschreibung eines Sensors auf Basis von /v1/statistics/gateways/{smId}."""

    value_fn: Callable[[dict[str, Any]], float | None] = lambda data: None


STATISTICS_SENSOR_DESCRIPTIONS: tuple[SolarManagerStatisticsSensorDescription, ...] = (
    SolarManagerStatisticsSensorDescription(
        key="self_consumption_energy",
        translation_key="self_consumption_energy",
        name="Eigenverbrauch",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        # API liefert Wh -> Umrechnung in kWh
        value_fn=lambda data: (
            data[KEY_SELF_CONSUMPTION] / 1000
            if data.get(KEY_SELF_CONSUMPTION) is not None
            else None
        ),
    ),
    SolarManagerStatisticsSensorDescription(
        key="self_consumption_rate",
        translation_key="self_consumption_rate",
        name="Eigenverbrauchsrate",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:home-lightning-bolt",
        suggested_display_precision=1,
        value_fn=lambda data: data.get(KEY_SELF_CONSUMPTION_RATE),
    ),
    SolarManagerStatisticsSensorDescription(
        key="autarchy_degree",
        translation_key="autarchy_degree",
        name="Autarkiegrad",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:home-battery",
        suggested_display_precision=1,
        value_fn=lambda data: data.get(KEY_AUTARCHY_DEGREE),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Richtet die Sensor-Entitäten für einen Config-Entry ein."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: SolarManagerDataUpdateCoordinator = entry_data[DATA_COORDINATOR]
    statistics_coordinator: SolarManagerStatisticsCoordinator = entry_data[
        DATA_STATISTICS_COORDINATOR
    ]
    sm_id = entry.data[CONF_SM_ID]

    entities: list[SensorEntity] = []

    for description in POWER_SENSOR_DESCRIPTIONS:
        entities.append(
            SolarManagerPowerSensor(coordinator, entry, sm_id, description)
        )

    for description in ENERGY_SENSOR_DESCRIPTIONS:
        entities.append(
            SolarManagerEnergySensor(coordinator, entry, sm_id, description)
        )

    for description in STATISTICS_SENSOR_DESCRIPTIONS:
        entities.append(
            SolarManagerStatisticsSensor(
                statistics_coordinator, entry, sm_id, description
            )
        )

    async_add_entities(entities)


def _device_info(sm_id: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, sm_id)},
        name="solar-manager",
        manufacturer=MANUFACTURER,
        model=MODEL,
    )


class SolarManagerPowerSensor(CoordinatorEntity[SolarManagerDataUpdateCoordinator], SensorEntity):
    """Sensor für einen Momentanwert (W, % etc.) direkt aus der API-Antwort."""

    entity_description: SolarManagerPowerSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SolarManagerDataUpdateCoordinator,
        entry: ConfigEntry,
        sm_id: str,
        description: SolarManagerPowerSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = _device_info(sm_id)

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.coordinator.data is None:
            return None
        last_update = self.coordinator.data.get(KEY_LAST_UPDATE)
        if last_update:
            return {"last_update": last_update}
        return None


class SolarManagerEnergySensor(
    CoordinatorEntity[SolarManagerDataUpdateCoordinator], RestoreEntity, SensorEntity
):
    """Berechnet einen laufenden kWh-Zähler aus den Momentanleistungswerten.

    Die Solar Manager API liefert nur Watt (Momentanleistung), keine
    Energiewerte. Diese Entität integriert die Leistung über die Zeit
    (Trapezregel: (P_alt + P_neu) / 2 * dt) und summiert das Ergebnis in kWh
    auf. Der Zählerstand wird über Neustarts von Home Assistant hinweg
    (RestoreEntity) wiederhergestellt, ähnlich einem echten Energiezähler.

    Der Zähler wird ausserdem täglich um Mitternacht (gemäss der in Home
    Assistant unter Einstellungen -> System -> Allgemein eingestellten
    Zeitzone) automatisch auf 0 zurückgesetzt, sodass er - wie ein
    Tagesenergiezähler - jeweils die seit Tagesbeginn produzierte/
    verbrauchte Energie zeigt.
    """

    entity_description: SolarManagerEnergySensorDescription
    _attr_has_entity_name = True
    _attr_suggested_display_precision = 3

    def __init__(
        self,
        coordinator: SolarManagerDataUpdateCoordinator,
        entry: ConfigEntry,
        sm_id: str,
        description: SolarManagerEnergySensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = _device_info(sm_id)

        self._total_kwh: float = 0.0
        self._last_power_w: float | None = None
        self._last_timestamp: datetime | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (
            None,
            "unknown",
            "unavailable",
        ):
            try:
                self._total_kwh = float(last_state.state)
            except (TypeError, ValueError):
                _LOGGER.debug(
                    "Konnte vorherigen Zustand von %s nicht wiederherstellen: %s",
                    self.entity_id,
                    last_state.state,
                )
                self._total_kwh = 0.0

        # Aktuellen Wert direkt nach dem Start einmal berechnen/anzeigen,
        # ohne dabei bereits Energie zu integrieren (kein "alter" Messpunkt).
        self._integrate(reset_baseline_only=True)

        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

        # Täglicher Reset auf 0 um Mitternacht, gemäss der in Home Assistant
        # konfigurierten Zeitzone (Einstellungen -> System -> Allgemein).
        # async_track_time_change wertet hour/minute/second immer in der
        # lokalen HA-Zeitzone aus.
        self.async_on_remove(
            async_track_time_change(
                self.hass,
                self._handle_midnight_reset,
                hour=0,
                minute=0,
                second=0,
            )
        )

    @callback
    def _handle_midnight_reset(self, now: datetime) -> None:
        """Setzt den Energiezähler um lokale Mitternacht auf 0 zurück."""
        _LOGGER.debug(
            "Setze %s um Mitternacht (Zeitzone: %s) auf 0 zurück",
            self.entity_id,
            dt_util.DEFAULT_TIME_ZONE,
        )
        self._total_kwh = 0.0
        # Baseline neu setzen, damit nicht die Leistung "vor Mitternacht"
        # noch in den neuen Tag hinein mitgerechnet wird.
        self._last_power_w = None
        self._last_timestamp = dt_util.utcnow()
        self.async_write_ha_state()

    def _handle_coordinator_update(self) -> None:
        self._integrate()
        self.async_write_ha_state()

    def _integrate(self, reset_baseline_only: bool = False) -> None:
        """Berechnet den kWh-Zuwachs seit dem letzten Datenpunkt."""
        data = self.coordinator.data
        if not data:
            return

        power_w = self.entity_description.power_value_fn(data)
        now = datetime.now(timezone.utc)

        if power_w is None:
            return

        # Negative Leistungswerte (z.B. Messrauschen) nicht als Energiezuwachs
        # werten - jede der vier Größen (Produktion/Verbrauch/Laden/Entladen)
        # ist als eigenständiger, nicht-negativer Fluss definiert.
        power_w = max(power_w, 0.0)

        if (
            not reset_baseline_only
            and self._last_power_w is not None
            and self._last_timestamp is not None
        ):
            dt_hours = (now - self._last_timestamp).total_seconds() / 3600.0
            if 0 < dt_hours < 1:  # Schutz vor riesigen Sprüngen (z.B. HA war down)
                avg_power_w = (self._last_power_w + power_w) / 2.0
                self._total_kwh += (avg_power_w * dt_hours) / 1000.0

        self._last_power_w = power_w
        self._last_timestamp = now

    @property
    def native_value(self) -> float:
        return round(self._total_kwh, 4)


class SolarManagerStatisticsSensor(
    CoordinatorEntity[SolarManagerStatisticsCoordinator], SensorEntity
):
    """Sensor auf Basis von /v1/statistics/gateways/{smId}.

    Fragt jeweils den Zeitraum von lokaler Mitternacht bis jetzt ab (siehe
    SolarManagerStatisticsCoordinator), daher setzen sich Eigenverbrauch,
    Eigenverbrauchsrate und Autarkiegrad automatisch - ganz ohne
    eigene Reset-Logik - täglich um Mitternacht zurück, da die Cloud-API
    dann selbst wieder bei 0 Wh für den neuen Tag beginnt.
    """

    entity_description: SolarManagerStatisticsSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SolarManagerStatisticsCoordinator,
        entry: ConfigEntry,
        sm_id: str,
        description: SolarManagerStatisticsSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = _device_info(sm_id)

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"period": "seit lokaler Mitternacht (heute)"}
