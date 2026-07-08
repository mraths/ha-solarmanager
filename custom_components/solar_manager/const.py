"""Constants for the Solar Manager integration."""

DOMAIN = "solar_manager"

CONF_SM_ID = "sm_id"
CONF_AUTH_METHOD = "auth_method"
CONF_API_KEY = "api_key"

AUTH_METHOD_PASSWORD = "password"
AUTH_METHOD_API_KEY = "api_key"

API_BASE_URL = "https://cloud.solar-manager.ch"
API_ENDPOINT_CHART_GATEWAY = "/v1/chart/gateway/{sm_id}"

# Laut Swagger (https://cloud.solar-manager.ch/swagger.json):
# Der API-Key wird wie ein Refresh-Token behandelt und hier gegen ein
# kurzlebiges Access-Token (Bearer, standardmässig 1h gültig) getauscht.
API_ENDPOINT_AUTH_REFRESH = "/v3/auth/refresh"
TOKEN_EXPIRY_BUFFER_SECONDS = 60  # Sicherheitsmarge vor Ablauf des Access-Tokens

# Standard-Abfrageintervall in Sekunden.
# Kann optional über die Optionen der Integration angepasst werden.
DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 10

CONF_SCAN_INTERVAL = "scan_interval"

MANUFACTURER = "Solar Manager AG"
MODEL = "Solar Manager Gateway"

# Keys innerhalb von coordinator.data
KEY_PRODUCTION = "production"
KEY_CONSUMPTION = "consumption"
KEY_BATTERY = "battery"
KEY_BATTERY_CAPACITY = "capacity"
KEY_BATTERY_CHARGING = "batteryCharging"
KEY_BATTERY_DISCHARGING = "batteryDischarging"
KEY_LAST_UPDATE = "lastUpdate"
KEY_ARROWS = "arrows"
