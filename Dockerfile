# syntax=docker/dockerfile:1
FROM python:3.13-slim

WORKDIR /app

# System deps for lxml and others
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python3", "chat.py", "--health"]

