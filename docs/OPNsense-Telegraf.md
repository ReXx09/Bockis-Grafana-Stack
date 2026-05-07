# OPNsense Telegraf Setup

Anleitung zur Konfiguration des Telegraf-Agents auf OPNsense für InfluxDB 2.x.

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
