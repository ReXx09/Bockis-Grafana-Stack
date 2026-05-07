# Grafana Dashboards

Folgende Community-Dashboards werden empfohlen.  
Import: Grafana WebUI → Dashboards → Import → Dashboard-ID eingeben.

| Dashboard        | ID    | Datasource     |
|-----------------|-------|----------------|
| OPNsense        | 13386 | InfluxDB 2.x   |
| Unraid          | 7233  | InfluxDB 2.x   |
| Raspberry Pi    | 10578 | InfluxDB 2.x   |
| WireGuard       | 12177 | InfluxDB 2.x   |
| Docker          | 1860  | InfluxDB 2.x   |

## Datasource einrichten

1. Grafana → Configuration → Data Sources → Add data source
2. InfluxDB auswählen
3. **Query Language: Flux** (für InfluxDB 2.x)
4. URL: `http://influxdb:8086`
5. Organisation: `home`
6. Token: `<INFLUXDB_ADMIN_TOKEN>` aus `.env`
7. Default Bucket: `homelab`
8. Save & Test

## Hinweise

- Dashboard 1860 (Docker) nutzt Prometheus-Format — optional.
- Für OPNsense-Dashboard ggf. Variables (`$host`, `$interface`) in Dashboard-Settings anpassen.
- Dashboard-JSONs können auch in `grafana/dashboards/*.json` gespeichert und per Provisioning geladen werden.
