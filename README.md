# Bockis Grafana Stack

Monitoring-Stack für Homelab: **Grafana + InfluxDB 2.x + Telegraf**

## Übersicht

| Komponente | Host        | Rolle                              |
|------------|-------------|-------------------------------------|
| Grafana    | Unraid      | Dashboard WebUI (Port 3000)        |
| InfluxDB   | Unraid      | Zeitreihendatenbank (Port 8086)    |
| Telegraf   | Raspi       | Metriken-Agent (Nebenwohnsitz)     |
| Telegraf   | OPNsense    | Metriken-Agent (Hauptwohnsitz)     |

## Überwachte Systeme

- **Raspberry Pi** — System, Netzwerk, WireGuard, Docker
- **OPNsense** — System, Interfaces, Firewall (pf), WireGuard
- **Unraid** — via Telegraf-Agent direkt auf dem Host

## Projektstruktur

```
Bockis-Grafana-Stack/
├── docker/
│   └── unraid/
│       ├── docker-compose.yml    # Grafana + InfluxDB Stack
│       ├── .env.example          # Konfigurationsvorlage
│       └── templates/            # Unraid XML Templates (Grafana/InfluxDB/Telegraf)
├── telegraf/
│   ├── raspi/
│   │   └── telegraf.conf         # Agent-Config für Raspberry Pi
│   ├── opnsense/
│       └── telegraf.conf         # Agent-Config für OPNsense
│   └── unraid/
│       └── telegraf.conf         # Agent-Config für Unraid Host
├── grafana/
│   ├── dashboards/
│   │   └── README.md             # Dashboard-IDs zum Importieren
│   └── provisioning/
│       ├── dashboards/
│       │   └── dashboards.yml
│       └── datasources/
│           └── datasource.yml
└── docs/
    ├── Setup-Anleitung.md        # Komplette Einrichtungsanleitung
    └── OPNsense-Telegraf.md      # OPNsense-spezifische Anleitung
```

## Schnellstart

```bash
cd docker/unraid/
cp .env.example .env
# .env mit eigenen Werten befüllen!
nano .env
docker compose pull
docker compose up -d
```

Danach: [docs/Setup-Anleitung.md](docs/Setup-Anleitung.md)

## Unraid XML Templates

Wenn du lieber direkt ueber Unraid-Container-Templates installierst (statt Compose), nutze:

- `docker/unraid/templates/influxdb2.xml`
- `docker/unraid/templates/grafana.xml`
- `docker/unraid/templates/telegraf.xml`

Die XMLs enthalten bereits Ports, Volumes und Variablen fuer:

- InfluxDB 2 Setup (User, Token, Org, Bucket)
- Grafana Admin + Influx Datasource-Provisioning
- Telegraf Unraid Host + Docker-Metriken

Hinweis: In den Templates musst du nur noch die CHANGEME-Werte ersetzen.
Import in Unraid: XML-Dateien nach `/boot/config/plugins/dockerMan/templates-user/` kopieren und dann in Docker → Add Container auswaehlen.

## Was jetzt automatisch passiert

- Grafana bekommt die InfluxDB-DataSource beim Start automatisch via Provisioning.
- Lokale Dashboard-JSON-Dateien in `grafana/dashboards/` werden automatisch geladen.
- Grafana startet erst, wenn InfluxDB als healthy gemeldet wird.

## Dashboards (Grafana Community)

| Dashboard    | ID    |
|-------------|-------|
| OPNsense    | 13386 |
| Unraid      | 7233  |
| Raspi       | 10578 |
| WireGuard   | 12177 |
| Docker      | 1860  |

---

*Copyright (c) 2026 Bocki — MIT License*
