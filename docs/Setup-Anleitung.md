# Setup-Anleitung — Bockis Grafana Stack

## Übersicht

```
Raspi (Nebenwohnsitz)          OPNsense (Hauptwohnsitz)
  Telegraf-Agent     ──────────────────►
                                           \
                                            InfluxDB 2.x  ──►  Grafana
                                           /             (Unraid)
  Unraid-System      ──────────────────►
```

**Ports:**
- InfluxDB: `8086`
- Grafana:  `3000`

---

## Schritt 1 — Unraid: Docker Stack starten

```bash
# Auf dem Unraid-Server (SSH oder Terminal)
cd /mnt/user/appdata/bockis-grafana-stack/

# .env aus Beispiel-Datei erstellen und anpassen
cp .env.example .env
nano .env
```

Wichtige Werte in `.env`:
- `INFLUXDB_ADMIN_PASSWORD` — sicheres Passwort
- `INFLUXDB_ADMIN_TOKEN` — zufälliger Token (`openssl rand -hex 32`)
- `GRAFANA_ADMIN_PASSWORD` — sicheres Passwort

```bash
# Stack starten
docker compose up -d
```

Prüfen:
```bash
docker compose ps
```

---

## Schritt 2 — InfluxDB initial einrichten

Nach dem ersten Start ist InfluxDB bereits über die `.env`-Variablen eingerichtet.

WebUI aufrufen: `http://<UNRAID-IP>:8086`
- Login: `admin` / `<INFLUXDB_ADMIN_PASSWORD>`
- Organisation: `home`, Bucket: `homelab` vorhanden

**Token notieren:** Data → API Tokens → Admin Token kopieren  
(oder aus `.env`: `INFLUXDB_ADMIN_TOKEN`)

---

## Schritt 3 — Telegraf auf Raspberry Pi installieren

```bash
# SSH auf Raspi
ssh pi@<RASPI-IP>

# Telegraf installieren
sudo apt update && sudo apt install -y telegraf

# Konfiguration kopieren
sudo cp /path/to/telegraf/raspi/telegraf.conf /etc/telegraf/telegraf.conf
sudo nano /etc/telegraf/telegraf.conf
```

Anpassen:
- `<UNRAID-IP>` → IP des Unraid-Servers
- `<INFLUXDB_ADMIN_TOKEN>` → Token aus Schritt 2

```bash
# Telegraf starten und aktivieren
sudo systemctl enable --now telegraf

# Test
sudo telegraf --config /etc/telegraf/telegraf.conf --test 2>&1 | head -30
```

Telegraf braucht Docker-Socket-Zugriff:
```bash
sudo usermod -aG docker telegraf
sudo systemctl restart telegraf
```

---

## Schritt 4 — Telegraf auf OPNsense einrichten

Siehe [docs/OPNsense-Telegraf.md](OPNsense-Telegraf.md) für die detaillierte Anleitung.

Kurzfassung:
1. `os-telegraf` Plugin installieren
2. Telegraf → Additional Configuration → InfluxDB 2.x Output einfügen
3. Inputs: CPU, Memory, Disk, Network, pf, Temp aktivieren
4. WireGuard-Input via Additional Configuration hinzufügen

---

## Schritt 5 — Grafana einrichten

WebUI: `http://<UNRAID-IP>:3000`  
Login: `admin` / `<GRAFANA_ADMIN_PASSWORD>`

### Datasource hinzufügen

1. Configuration → Data Sources → Add data source → InfluxDB
2. Query Language: **Flux**
3. URL: `http://influxdb:8086`
4. Organisation: `home`
5. Token: `<INFLUXDB_ADMIN_TOKEN>`
6. Default Bucket: `homelab`
7. Save & Test

### Dashboards importieren

Dashboards → Import → ID eingeben:

| Dashboard     | ID    |
|---------------|-------|
| OPNsense      | 13386 |
| Unraid        | 7233  |
| Raspberry Pi  | 10578 |
| WireGuard     | 12177 |
| Docker        | 1860  |

---

## Backup

Wichtige Volumes sichern:
```
docker/unraid/data/influxdb/        # Alle Metriken
docker/unraid/data/grafana/         # Dashboards, Einstellungen
docker/unraid/.env                  # Zugangsdaten
```

---

## Fehlerbehebung

```bash
# Logs prüfen
docker compose logs influxdb
docker compose logs grafana

# Telegraf auf Raspi
sudo journalctl -u telegraf -f

# Verbindungstest (von Raspi zu InfluxDB)
curl -I http://<UNRAID-IP>:8086/health
```
