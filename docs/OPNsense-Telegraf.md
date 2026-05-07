# OPNsense Telegraf Setup

Anleitung zur Konfiguration des Telegraf-Agents auf OPNsense für InfluxDB 2.x.

## Benoetige ich weitere Addons auf OPNsense?

Kurzantwort: Fuer den Standardbetrieb brauchst du nur ein Addon.

| Ziel | Addon auf OPNsense | Pflicht |
|------|---------------------|---------|
| Telegraf Metriken an InfluxDB senden | `os-telegraf` | Ja |
| Block/Allow auf Weltkarte (via Syslog an Unraid + GeoIP in Telegraf auf Unraid) | keines zusaetzlich | Nein |

Optional je nach Funktionsumfang:

| Zusatzfunktion | Addon auf OPNsense | Hinweis |
|---------------|---------------------|---------|
| IDS/IPS Metriken und Events | `os-suricata` | Nur wenn IDS/IPS genutzt wird |
| NetFlow/IPFIX Flows | `os-netflow` | Fuer Flow-Analysen, nicht Pflicht fuer Basis-Weltkarte |
| Erweiterte Log-Weiterleitung | `os-syslog-ng` (optional) | Nur noetig bei komplexem Logging-Routing |

Wichtig: Die GeoIP-Anreicherung fuer die Weltkarte passiert in diesem Projekt auf Unraid in Telegraf, nicht auf OPNsense.

## Plugin installieren

1. OPNsense WebUI → **System → Firmware → Plugins**
2. `os-telegraf` suchen und installieren
3. Neustart nicht notwendig

---

## Telegraf konfigurieren

Navigiere zu **System → Telegraf**.

### Tab: General

| Feld                | Wert                  |
|---------------------|-----------------------|
| Enable              | ✅                    |
| Interval            | 10                    |
| Hostname override   | `opnsense-hauptwohnsitz` |

### Tab: Output

OPNsense os-telegraf bietet standardmäßig nur InfluxDB 1.x in der GUI.  
Für **InfluxDB 2.x** gibt es zwei Wege:

---

## Weg A — DBRP-Kompatibilitätsmodus (empfohlen)

InfluxDB 2.x kann InfluxDB-1.x-Schreibanfragen entgegennehmen.

### 1. DBRP-Mapping in InfluxDB erstellen

Über die InfluxDB WebUI (`http://<UNRAID-IP>:8086`):

1. Load Data → DBRP → Create DBRP Mapping
2. Bucket: `homelab`
3. Database: `telegraf`
4. Retention Policy: `autogen`

Alternativ via CLI:
```bash
influx v1 dbrp create \
  --bucket-id <BUCKET-ID> \
  --db telegraf \
  --rp autogen \
  --default
```

### 2. InfluxDB 1.x Authorization erstellen

```bash
influx v1 auth create \
  --username telegraf-opnsense \
  --password <PASSWORT> \
  --write-bucket homelab
```

### 3. OPNsense Telegraf Output konfigurieren

GUI → Telegraf → Output → InfluxDB:

| Feld          | Wert                            |
|---------------|---------------------------------|
| URL           | `http://<UNRAID-IP>:8086`       |
| Database      | `telegraf`                      |
| Username      | `telegraf-opnsense`             |
| Password      | `<PASSWORT>`                    |

---

## Weg B — Direkt via Token (Additional Configuration)

Wenn Weg A nicht funktioniert oder bevorzugt wird.

1. OPNsense → Telegraf → **Additional Configuration**
2. Folgendes einfügen:

```toml
[[outputs.influxdb_v2]]
  urls = ["http://<UNRAID-IP>:8086"]
  token = "<INFLUXDB_ADMIN_TOKEN>"
  organization = "home"
  bucket = "homelab"
```

3. GUI Output deaktivieren (kein Standard-Output konfigurieren)

---

## Inputs aktivieren

GUI → Telegraf → Input:

| Input        | Aktivieren |
|--------------|-----------|
| CPU          | ✅        |
| Memory       | ✅        |
| Disk         | ✅        |
| Network      | ✅        |
| Processes    | ✅        |
| pf (Firewall)| ✅        |
| Temp         | ✅        |

Für WireGuard: **Additional Configuration** nötig:
```toml
[[inputs.wireguard]]
  devices = ["wg0"]
```

---

## Testen

```bash
# Auf OPNsense Shell:
telegraf --config /usr/local/etc/telegraf.conf --test | head -50
```

## Firewall-Regel prüfen

OPNsense → Firewall → Regeln: Port 8086/TCP zur Unraid-IP muss erlaubt sein.

---

## Block/Allow auf Weltkarte (Grafana Geomap)

Ja, das geht. Fuer eine Weltkarte brauchst du neben Telegraf auch GeoIP-Anreicherung der Quell-IP.

### Zielbild

1. OPNsense sendet Firewall-Logs (filterlog) per Syslog an Unraid
2. Telegraf auf Unraid nimmt Syslog an
3. Telegraf reichert externe Source-IPs mit GeoIP (Lat/Lon, Land) an
4. InfluxDB speichert Felder wie action, src_ip, country, latitude, longitude
5. Grafana Geomap zeigt block rot, pass/allow gruen

### Wichtige Grenzen

- Private RFC1918-Adressen sind nicht geolokalisierbar
- Nicht jeder Logeintrag hat verwertbare Source-IP
- "Komplett" im Sinne aller OPNsense-Subsysteme ist mit Telegraf allein nicht realistisch

### Umsetzungsschritte

1. OPNsense: System → Settings → Logging / Targets
2. Remote Syslog Target auf Unraid setzen, z. B. udp 5514
3. Nur Firewall-Logs (filterlog) aktivieren
4. Telegraf auf Unraid um Syslog-Input erweitern
5. GeoLite2-City Datenbank (mmdb) bereitstellen und in Telegraf einbinden
6. In Grafana Geomap Panel erstellen und nach action aufteilen

### Grafana Geomap Empfehlung

- Query A: action = block, Farbe rot
- Query B: action = pass oder allow, Farbe gruen
- Punkte nach count aggregieren, z. B. pro Land oder pro Koordinate

### Security-Hinweis

- Fuer Telegraf immer einen eigenen Write-Token nutzen, nicht den Influx Admin-Token.
