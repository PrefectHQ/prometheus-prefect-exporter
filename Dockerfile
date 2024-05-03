FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY ./ ./

RUN pip install uv
RUN uv venv
RUN uv pip install --system -r requirements.txt

EXPOSE 8000
USER nobody

CMD [ "python", "main.py" ]
