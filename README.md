# Prometheus Prefect Exporter

A Prometheus exporter for [Prefect](https://www.prefect.io/) metrics, written in Python. Originally contributed by @ialejandro!

## Usage

By default `prometheus-prefect-exporter` will listen on port `8000`.

While the [default scrape interval](https://prometheus.io/docs/instrumenting/writing_exporters/#scheduling)
in Prometheus is 10 seconds, we recommend a longer interval:

- High-frequency environments: 30s
- Standard monitoring: 60s
- Low-change environments: 120s

The exporter performs several endpoints, and certain endpoints may use pagination and therefore require
multiple API calls. A longer scrape interval ensures that the exporter does not overwhelm the Prefect API
server and create unnecessary load.

### Installing released versions

**Docker**

```bash
docker run -d \
  -p 8000:8000 \
  -e PREFECT_API_URL=<PREFECT_ENDPOINT> \
  prefecthq/prometheus-prefect-exporter:latest
```

**Helm**

```bash
helm repo add prefect https://prefecthq.github.io/prefect-helm
helm search repo prefect
helm install prometheus-prefect-exporter prefect/prometheus-prefect-exporter
```

### Installing development versions

You will need to have a Prefect Server up and running for the exporter to communicate with. Follow these steps to set one up, or skip to step 3.

1. Install Prefect Server

```bash
helm repo add prefect https://prefecthq.github.io/prefect-helm
helm search repo prefect
helm install prefect-server prefect/prefect-server
```

2. Port forward the api to your localhost:

```bash
kubectl port-forward svc/prefect-server 4200:4200
```

3. Clone repository

```bash
git clone https://github.com/PrefectHQ/prometheus-prefect-exporter.git
```

4. Change to this directory

```bash
cd prometheus-prefect-exporter`
```

5. Setup a virtual environment of your choice & install dependencies

```bash
virtualenv prom-exporter
source prom-exporter/bin/activate
pip install -r requirements.txt
python main.py
```

#### Using Docker Compose

Alternatively, you can use the [Docker Compose configuration](./compose.yml)
to stand up the exporter alongside Prefect and Prometheus.

To get started, run:

```bash
docker compose up -d
```

Confirm the services are running and healthy:

```
docker compose ps
```

You can now reach each service locally:

- Prefect: http://localhost:4200
- Exporter: http://localhost:8000
- Prometheus: http://localhost:9090

## Configuration

You can modify environment variables to change the behavior of the exporter.
- An API Key is only required for auth-enabled, on-prem, self-managed solutions.
- An API key is not required for open-source or Prefect Server.
- If an API key and API auth string are provided, then the API key takes precedence.

| Environment Variable | Description | Default |
| --- | --- | --- |
| `LOG_LEVEL` | Logging level | `INFO` |
| `MAX_RETRIES` | Number of retries to attempt when fetching metrics from Prefect API | `3` |
| `METRICS_ADDR` | Address to expose metrics on | `0.0.0.0` |
| `METRICS_PORT` | Port to expose metrics on | `8000` |
| `OFFSET_MINUTES` | Number of minutes to offset the start time when fetching metrics from Prefect API | `5` |
| `PREFECT_API_URL` | Prefect API URL | `https://localhost:4200/api` |
| `PREFECT_API_KEY` | Prefect API key (Optional) | `""` |
| `PREFECT_API_AUTH_STRING` | Prefect API auth string, automatically base64-encoded (Optional) | `""` |
| `PREFECT_CSRF_ENABLED` | Enable compatibilty with Prefect Servers using CSRF protection | `False` |
| `PAGINATION_ENABLED` | Enable pagination for API requests. Can help reduce server load and avoid timeouts. Can be disabled on very small instances. | `True` |
| `PAGINATION_LIMIT` | Number of results to retrieve per request when pagination is enabled. Consider lowering this value for large instances to make more, but smaller, requests. | `200` |
| `FAILED_RUNS_OFFSET_MINUTES` | Time window in minutes for the `prefect_deployment_last_failed_flow_run` metric. Failed runs older than this window are ignored. | `10080` (7 days) |
| `FAILED_RUNS_LIMIT` | Maximum number of recent failed runs to expose per deployment in `prefect_deployment_last_failed_flow_run`. | `10` |

## Contributing

Contributions to the Prometheus Prefect Exporter are always welcome. Fork this repository and commit changes to your local repository. You can then open a pull request against this upstream repository that the team will review.

To get started, ensure you have the required dependencies installed:

```shell
mise install
```

Be sure to run `pre-commit install` before starting any development. [`pre-commit`](https://pre-commit.com/)
will help catch simple issues before committing.

### Documentation

Please make sure that your changes have been linted and the documentation has been updated. The easiest way to accomplish this is by installing [`pre-commit`](https://pre-commit.com/).

### Opening a pull request

A helpful pull request explains _what_ changed and _why_ the change is important. Please take time to make your pull request descriptions as helpful as possible.

For pull requests from a fork, please follow [the GitHub instructions](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/working-with-forks/allowing-changes-to-a-pull-request-branch-created-from-a-fork) to allow maintainers to push commits to your branch.
