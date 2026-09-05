# Playwright's image ships Chromium + its system libs; the tag must match the pinned playwright version.
FROM mcr.microsoft.com/playwright/python:v1.58.0-noble AS base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

# Deploy gate: the runtime stage copies a marker this stage only produces on a green suite.
FROM base AS test
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt && pytest -q && touch /tests-passed

FROM base AS runtime
COPY --from=test /tests-passed /tests-passed
ENV REDAT_DATA_DIR=/data
EXPOSE 8200
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8200/healthz', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "redat.app:app", "--host", "0.0.0.0", "--port", "8200"]
