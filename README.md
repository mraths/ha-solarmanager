# Solar Manager – Home Assistant Custom Integration

Home-Assistant-Integration für die [Solar Manager Cloud API](https://cloud.solar-manager.ch/swagger.json).

Nutzt den Endpoint:

```
GET /v1/chart/gateway/{smId}
```

## Features

- Einrichtung komplett über die Home Assistant UI (Config Flow)
- Zwei wählbare Authentifizierungsmethoden:
  - **Benutzername + Passwort** (HTTP Basic Auth) — Pflichtfelder: Benutzername, Passwort, smId
  - **API-Key** — Pflichtfelder: API-Key, smId
- Sensoren für Momentanleistung (Watt):
  - Produktion
  - Verbrauch
  - Batterie Ladeleistung
  - Batterie Entladeleistung
  - Batteriekapazität (%)
- Zusätzliche **kWh-Sensoren** (siehe Hinweis unten):
  - Produktion (kWh)
  - Verbrauch (kWh)
  - Batterie Ladeenergie (kWh)
  - Batterie Entladeenergie (kWh)
  - Alle vier setzen sich **täglich um lokale Mitternacht automatisch auf 0 zurück**
    (gemäss der unter Home Assistant → Einstellungen → System → Allgemein
    eingestellten Zeitzone), sodass sie jeweils die seit Tagesbeginn
    produzierte/verbrauchte Energie zeigen.
- Zusätzliche Sensoren für **Autarkie und Eigenverbrauch** (seit lokaler
  Mitternacht, direkt von der Solar Manager Cloud berechnet):
  - Eigenverbrauch (kWh)
  - Eigenverbrauchsrate (%)
  - Autarkiegrad (%)
- Optionales, konfigurierbares Abfrageintervall (Standard 30 s)

## Wichtiger Hinweis zu den kWh-Werten

Der Endpoint `/v1/chart/gateway/{smId}` liefert ausschliesslich **Momentanleistungen in Watt**,
keine Energie in kWh. Diese Integration berechnet die kWh-Sensoren (Produktion,
Verbrauch, Batterie Laden/Entladen) daher selbst, indem die Leistung über die
Zeit integriert wird (Trapezregel: `(P_alt + P_neu) / 2 * Δt`). Der Zählerstand:

- startet bei `0` bei der Erstinstallation,
- wird bei jedem Update-Zyklus weitergezählt,
- übersteht Neustarts von Home Assistant (Wiederherstellung des letzten Wertes),
- wird **täglich um lokale Mitternacht automatisch auf `0` zurückgesetzt** –
  massgebend ist dabei die in Home Assistant konfigurierte Zeitzone
  (Einstellungen → System → Allgemein → Zeitzone), nicht UTC.

Die Genauigkeit hängt vom gewählten Abfrageintervall ab – ein kürzeres
Intervall (z.B. 15–30 s) liefert eine präzisere Energie-Integration als ein
sehr langes Intervall. Für eine "offizielle", exaktere kWh-Historie
(z.B. für die Home-Assistant-Energie-Dashboard-Ansicht) kannst du diese
Sensoren zusätzlich mit dem eingebauten Helfer **"Integration – Riemann-Summe"**
verfeinern oder direkt als Energie-Quelle im Energie-Dashboard eintragen,
da sie bereits `device_class: energy` und `state_class: total_increasing`
besitzen.

## Autarkiegrad und Eigenverbrauchsrate

Diese beiden Werte werden **nicht** selbst berechnet, sondern direkt vom
offiziellen Endpoint `GET /v1/statistics/gateways/{smId}` bezogen – dort
berechnet Solar Manager sie serverseitig aus den historischen Daten der
Anlage. Die Integration fragt dafür jeweils den Zeitraum "seit lokaler
Mitternacht bis jetzt" ab (Standard-Intervall: alle 5 Minuten, konfigurierbar
über `STATISTICS_SCAN_INTERVAL` in `const.py`):

- **Eigenverbrauch (kWh)** – heute selbst verbrauchte, selbst produzierte Energie
- **Eigenverbrauchsrate (%)** – Anteil der Produktion, der direkt selbst verbraucht wurde
- **Autarkiegrad (%)** – Anteil des Verbrauchs, der durch eigene Produktion gedeckt wurde

Da für diese Werte immer ab lokaler Mitternacht neu abgefragt wird, "resetten"
sie sich automatisch jeden Tag – ganz ohne eigene Reset-Logik in der Integration.

## Authentifizierung: Benutzername/Passwort vs. API-Key

Bei der Einrichtung wählst du zunächst die Methode aus:

1. **Benutzername + Passwort** – klassische Anmeldung per HTTP Basic Auth.
2. **API-Key** – wird von Solar Manager als sicherere Variante empfohlen.
   Die Integration behandelt den API-Key intern wie einen Refresh-Token:
   - Bei Bedarf wird `POST /v3/auth/refresh` mit
     `{"grant_type": "refresh_token", "refresh_token": "<API-Key>"}` aufgerufen.
   - Die Antwort enthält ein kurzlebiges `access_token` (Standard: 1h gültig),
     das anschliessend als `Authorization: Bearer <access_token>` für alle
     Anfragen genutzt wird.
   - Das Access-Token wird automatisch erneuert, bevor es abläuft
     (inkl. einer Sicherheitsmarge von 60 Sekunden), sodass der API-Key selbst
     nicht bei jeder einzelnen Anfrage mitgeschickt werden muss.
   - Deinen API-Key erhältst/verwaltest du in deinem Solar Manager
     Cloud-Konto (Bereich API-Zugriff/Einstellungen).

Beide Methoden können jederzeit über **Integration löschen + neu einrichten**
gewechselt werden; ein nachträglicher Wechsel innerhalb eines bestehenden
Config-Entries ist aktuell nicht vorgesehen.

## Installation

### Manuell

1. Repo klonen bzw. in GitLab ablegen.
2. Den Ordner `custom_components/solar_manager` in das Verzeichnis
   `<config>/custom_components/` deiner Home-Assistant-Installation kopieren.
3. Home Assistant neu starten.
4. **Einstellungen → Geräte & Dienste → Integration hinzufügen → "Solar Manager"** auswählen.
5. Benutzername, Passwort und smId eingeben.

### Über HACS (Custom Repository)

1. HACS → Integrationen → Menü (⋮) → **Benutzerdefinierte Repositories**.
2. URL dieses GitLab-Repos eintragen, Kategorie **Integration**.
3. "Solar Manager" installieren, Home Assistant neu starten.
4. Integration wie oben über die UI einrichten.

## Konfiguration ändern

Nach der Einrichtung kann über **Einstellungen → Geräte & Dienste →
Solar Manager → Konfigurieren** das Abfrageintervall angepasst werden.

## Projektstruktur

```
custom_components/solar_manager/
├── __init__.py        # Setup/Teardown des Config Entry
├── api.py              # HTTP-Client (Basic Auth) für die Solar Manager API
├── config_flow.py       # UI Config Flow (Username/Passwort/smId, Optionen)
├── const.py             # Konstanten
├── coordinator.py        # 2 DataUpdateCoordinators (Chart-Polling + Statistik-Polling)
├── manifest.json
├── sensor.py             # Leistung, kWh (Mitternachts-Reset), Autarkie/Eigenverbrauch
├── strings.json
└── translations/
    ├── de.json
    └── en.json
```

## Bekannte Einschränkungen

- Es wird aktuell nur der Endpoint `/v1/chart/gateway/{smId}` genutzt.
  Weitere Endpoints (z.B. `/v3/users/{smId}/data/stream`,
  `/v1/statistics/gateways/{smId}`, Steuerungs-Endpoints für Wallbox,
  Wärmepumpe, Batterie etc.) sind in dieser Version **nicht** implementiert,
  können aber nach demselben Muster (`api.py` + zusätzliche Coordinator/
  Sensor-Klassen) ergänzt werden.
- Authentifizierung erfolgt per HTTP Basic Auth (Username/Passwort).
  Solar Manager empfiehlt für produktive/dauerhafte Integrationen
  offiziell die Nutzung von **API-Keys** mit `/v3/auth/refresh`
  (JWT Access Token). Das kann bei Bedarf nachgerüstet werden.

## Lizenz

MIT – siehe [LICENSE](LICENSE).
