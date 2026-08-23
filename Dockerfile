# DropOS — backend + SPA in one container.
# The Playwright base image ships Chromium and its system libraries so the
# CSSBuy scraper works headless inside the container.
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

WORKDIR /app

# Python dependencies
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt \
 && python -m playwright install chromium

# Application
COPY backend/ backend/

# Runtime data (embedded DB if no DATABASE_URL, collages, cleaned images, secret)
ENV DROPOS_DATA_DIR=/data
VOLUME ["/data"]

ENV APP_ENV=production
EXPOSE 8000

WORKDIR /app/backend
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)" || exit 1
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
