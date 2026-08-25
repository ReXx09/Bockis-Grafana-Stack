# Bocki Grafana AIO Manager

The manager is the only container installed by the Unraid template. It stores its state below `/data`, exposes the setup UI on port 8800, and will manage only the five services listed in `aio/services.py`.

## Local smoke test

```powershell
python -m aio.app --bind 127.0.0.1 --port 8800 --data-dir .\aio-data
```

Open `http://127.0.0.1:8800`. The Docker socket is optional for the initial setup UI; service actions report a clear error until the manager runs with `/var/run/docker.sock` mounted.
