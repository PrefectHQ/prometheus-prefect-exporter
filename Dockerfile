FROM python:3.11-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY ["requirements.txt", "./"]

RUN pip install uv
RUN uv venv
RUN uv pip install --system -r requirements.txt

COPY ["./", "./"]

EXPOSE 8000
USER nobody

CMD [ "python", "main.py" ]
