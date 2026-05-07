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
│       └── .env.example          # Konfigurationsvorlage
├── telegraf/
│   ├── raspi/
│   │   └── telegraf.conf         # Agent-Config für Raspberry Pi
│   └── opnsense/
│       └── telegraf.conf         # Agent-Config für OPNsense
├── grafana/
│   └── dashboards/
│       └── README.md             # Dashboard-IDs zum Importieren
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
docker compose up -d
```

Danach: [docs/Setup-Anleitung.md](docs/Setup-Anleitung.md)

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
