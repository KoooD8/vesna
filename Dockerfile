# syntax=docker/dockerfile:1
FROM python:3.13-slim

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

# System deps for lxml and others
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python3", "chat.py", "--health"]

