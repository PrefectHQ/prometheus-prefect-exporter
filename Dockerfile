FROM python:3.11-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY ["./Pipfile", "./Pipfile.lock", "./"]

RUN python -m pip install --upgrade pip --no-cache-dir && \
    pip install --no-cache-dir pipenv && \
    pipenv sync --clear --system

COPY ["./", "./"]

EXPOSE 8000

CMD [ "python", "main.py" ]