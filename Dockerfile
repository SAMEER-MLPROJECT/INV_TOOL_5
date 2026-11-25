FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SAKSHYA_WORKSPACE=/data/workspace \
    PORT=8000

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY sakshya ./sakshya

RUN useradd --create-home sakshya && mkdir -p /data/workspace && chown -R sakshya /data
USER sakshya

EXPOSE 8000
CMD ["sh", "-c", "uvicorn sakshya.api.app:app --host 0.0.0.0 --port ${PORT}"]
