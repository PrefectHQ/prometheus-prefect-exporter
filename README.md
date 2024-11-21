# Prometheus Prefect Exporter

A Prometheus exporter for [Prefect](https://www.prefect.io/) metrics, written in Python. Originally contributed by @ialejandro!

## Usage

By default `prometheus-prefect-exporter` will listen on port `8000`.

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

| Environment Variable | Description | Default |
| --- | --- | --- |
| `LOG_LEVEL` | Logging level | `INFO` |
| `MAX_RETRIES` | Number of retries to attempt when fetching metrics from Prefect API | `3` |
| `METRICS_PORT` | Port to expose metrics on | `8000` |
| `OFFSET_MINUTES` | Number of minutes to offset the start time when fetching metrics from Prefect API | `5` |
| `PREFECT_API_URL` | Prefect API URL | `https://localhost:4200/api` |
| `PREFECT_API_KEY` | Prefect API KEY (Optional) | `""` |
| `PREFECT_CSRF_ENABLED` | Enable compatibilty with Prefect Servers using CSRF protection | `False` |
| `PAGINATION_ENABLED` | Enable pagination usage. (Uses more resources) | `True` |
| `PAGINATION_LIMIT` | Pagination limit | `200` |
| `PREFECT_API_USER` | Used in combination with the `PREFECT_API_PASSWORD` envrionment variable to configure basic auth. If a `PREFECT_API_KEY` is based then the system will prefer the bearer token method. | `""` |
| `PREFECT_API_PASSWORD` | Passes a password for basic auth | `""` |
| `COLLECT_HIGH_CARDINALITY` | Boolean that configures the system to either collect or ignore high cardinality metrics | `True` |


## Contributing

Contributions to the Prometheus Prefect Exporter is always welcome! We welcome your help - whether it's adding new functionality, tweaking documentation, or anything in between. In order to successfully contribute, you'll need to fork this repository and commit changes to your local prometheus-prefect-exporter repo. You can then open a PR against this upstream repo that the team will review!

### Documentation

Please make sure that your changes have been linted & the documentation has been updated.  The easiest way to accomplish this is by installing [`pre-commit`](https://pre-commit.com/).

### Testing & validation

Make sure that any new functionality is well tested!  You can do this by installing the exporter locally, see [above](https://github.com/PrefectHQ/prometheus-prefect-exporter#installing-development-versions) for how to do this.

### Opening a PR

A helpful PR explains WHAT changed and WHY the change is important. Please take time to make your PR descriptions as helpful as possible. If you are opening a PR from a forked repository - please follow [these](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/working-with-forks/allowing-changes-to-a-pull-request-branch-created-from-a-fork) docs to allow `prometheus-prefect-exporter` maintainers to push commits to your local branch.
