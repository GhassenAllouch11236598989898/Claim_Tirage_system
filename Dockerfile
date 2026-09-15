FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY claims_triage/ /app/claims_triage/

# Environment
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "claims_triage.api:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
