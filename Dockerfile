FROM python:3.15-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

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
