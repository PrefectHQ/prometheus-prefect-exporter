# Prometheus Prefect Exporter

A Prometheus exporter for [Prefect.io](https://www.prefect.io/) metrics, written in Python.

## Installation and usage

By default `prometheus-prefect-exporter` will listen on port `8000`.

### Docker

```bash
docker run -d \
  -p 8000:8000 \
  -e PREFECT_API_URL=<PREFECT_ENDPOINT> \
  devopsia/prometheus-prefect-exporter:latest
```

## Configuration

Can modify environment variables to change the behavior of the exporter.

| Environment Variable | Description | Default |
| --- | --- | --- |
| `LOG_LEVEL` | Logging level | `INFO` |
| `MAX_RETRIES` | Number of retries to attempt when fetching metrics from Prefect API | `3` |
| `METRICS_PORT` | Port to expose metrics on | `8000` |
| `OFFSET_MINUTES` | Number of minutes to offset the start time when fetching metrics from Prefect API | `5` |
| `PREFECT_API_URL` | Prefect API URL | `https://localhost/api` |
| `PREFECT_API_KEY` | Prefect API KEY (Optional) | `""` |

## Local build and running

Pre-requisites:

* Python 3.11
* Pipenv

Running:

```bash
git clone https://github.com/devops-ia/prometheus-prefect-exporter.git
cd prometheus-prefect-exporter
pipenv sync
pipenv shell
python main.py
```
