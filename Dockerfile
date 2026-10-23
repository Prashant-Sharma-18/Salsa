# --- Build the frontend -------------------------------------------------------
FROM node:26.11-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- Python runtime -----------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FLASK_APP=wsgi.py FRONTEND_DIST=/app/frontend_dist
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist ./frontend_dist
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser
EXPOSE 8000
# Apply migrations, then serve API + built frontend from one origin.
CMD ["sh", "-c", "flask db upgrade && gunicorn --bind 0.0.0.0:8000 --workers 3 --access-logfile - wsgi:app"]
