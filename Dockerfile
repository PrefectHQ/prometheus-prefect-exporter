FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY ./ ./

RUN pip install --upgrade pip
RUN pip install \
      --disable-pip-version-check \
      --no-cache-dir \
      --no-color \
      --requirement requirements.txt

EXPOSE 8000
USER nobody

CMD [ "python", "main.py" ]
