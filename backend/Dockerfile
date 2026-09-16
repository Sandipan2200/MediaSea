FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/mediasaver

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Run as non-root: least privilege inside the container too.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /srv/mediasaver
USER appuser

EXPOSE 8000

# Single worker by default; scale horizontally behind a load balancer.
# (Rate limiter is in-memory: use sticky sessions or a Redis swap for replicas.)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
