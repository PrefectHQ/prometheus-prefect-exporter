FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

ENV PREFECT_HOME=/app
ENV PREFECT_LOGGING_EXTRA_LOGGERS=prometheus-prefect-exporter
ENV PREFECT_LOGGING_TO_API_ENABLED=False

WORKDIR /app

COPY requirements.txt ./
RUN pip install \
      --disable-pip-version-check \
      --no-cache-dir \
      --no-color \
      --requirement requirements.txt

COPY ./ ./

EXPOSE 8000
USER nobody

CMD [ "python", "main.py" ]
