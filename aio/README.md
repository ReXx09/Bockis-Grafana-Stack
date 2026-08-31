# Bocki Grafana AIO Manager

The manager is the only container installed by the Unraid template. It stores its state below `/data`, exposes the setup UI on port 8800, and will manage only the five services listed in `aio/services.py`.

## Local smoke test

```powershell
python -m aio.app --bind 127.0.0.1 --port 8800 --data-dir .\aio-data
```

Open `http://127.0.0.1:8800`. The Docker socket is optional for the initial setup UI; service actions report a clear error until the manager runs with `/var/run/docker.sock` mounted.

## Manager aktualisieren

Der Manager aktualisiert sich nicht selbst. Nach einem neuen GHCR-Image in Unraid unter **Docker** beim Container `bocki-grafana-aio` **Force Update** ausfuehren. Die Konfiguration und Daten bleiben im Appdata-Mount erhalten. Danach die WebUI neu laden und die Dienststatus pruefen.

## Login

Die WebUI ist per HTTP Basic-Auth geschuetzt. Benutzername/Passwort koennen ueber die Container-Variablen `AIO_ADMIN_USER` / `AIO_ADMIN_PASSWORD` gesetzt werden. Ohne `AIO_ADMIN_PASSWORD` wird beim ersten Start ein zufaelliges Passwort erzeugt, unter `/data/admin_password.txt` gespeichert und einmalig im Container-Log ausgegeben.

## Dienste-Aktionen

Pro Dienst stehen in der Tabelle Buttons fuer Start/Stop/Restart/Update sowie ein Log-Viewer zur Verfuegung. Beim Update wird das Image neu gezogen und angezeigt, ob sich die Image-ID geaendert hat (Neustart des Dienstes noetig, um das neue Image zu verwenden).

## Stack neu erstellen

Der Button **Stack neu erstellen** entfernt und erstellt die fuenf vom Manager verwalteten Fachcontainer mit den aktuellen Images und der aktuellen Konfiguration neu. Vorher werden `config.json`, das Admin-Geheimnis und die generierten Dateien unter `/data/backups/` gesichert. Die persistenten Bind-Mounts unter `AIO_HOST_DATA_DIR` werden nicht geloescht. Der Manager-Container selbst bleibt unter Kontrolle von Unraid und wird durch diese Funktion nicht ersetzt.
