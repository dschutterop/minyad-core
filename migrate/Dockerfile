FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY migrate/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY migrate /app
RUN groupadd --gid 1000 minyad \
    && useradd --uid 1000 --gid minyad --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin minyad
USER 1000:1000
CMD ["alembic", "upgrade", "head"]
