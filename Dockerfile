# Summit Translate — backend container for Cloud Run
FROM python:3.12-slim

# No .pyc files, unbuffered logs (so Cloud Run captures them live)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

# Install deps first so this layer caches when only app code changes
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code only (frontend/ and .env are excluded via .dockerignore)
COPY backend/ .

EXPOSE 8080
# main.py reads $PORT (Cloud Run injects it); binds 0.0.0.0
CMD ["python", "main.py"]