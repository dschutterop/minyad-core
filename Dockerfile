FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt alembic.ini ./
RUN pip install --no-cache-dir -r requirements.txt
COPY migrations ./migrations
COPY minyad ./minyad

CMD ["python", "-m", "minyad.api"]
