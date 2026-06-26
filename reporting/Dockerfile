FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY shared /app/shared
COPY reporting /app/module
RUN groupadd --gid 1000 minyad \
    && useradd --uid 1000 --gid minyad --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin minyad
WORKDIR /app/module
USER 1000:1000
CMD ["python", "main.py"]
