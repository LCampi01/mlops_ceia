FROM python:3.12-slim

WORKDIR /app
COPY . .
COPY requirements.txt /requirements.txt

RUN apt-get update && apt-get install -y --no-install-recommends curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r /requirements.txt

EXPOSE 8800
