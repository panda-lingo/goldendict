FROM python:3.12-slim AS wheels

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       gcc \
       libc6-dev \
       liblzo2-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt requirements-dev.txt ./
RUN pip wheel --disable-pip-version-check --no-cache-dir --wheel-dir /wheels -r requirements-dev.txt

FROM python:3.12-slim AS test

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends liblzo2-2 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /work
COPY --from=wheels /wheels /wheels
COPY requirements.txt requirements-dev.txt ./
RUN pip install --disable-pip-version-check --no-cache-dir --no-index --find-links=/wheels -r requirements-dev.txt \
    && rm -rf /wheels
COPY app ./app
COPY tests ./tests
COPY pyproject.toml ./
CMD ["python", "-m", "pytest"]

FROM python:3.12-slim AS runtime

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends liblzo2-2 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 goldendict \
    && useradd --system --uid 10001 --gid goldendict --home-dir /app goldendict \
    && mkdir -p /app /dictionaries \
    && chown -R goldendict:goldendict /app /dictionaries

WORKDIR /app
COPY --from=wheels /wheels /wheels
COPY requirements.txt ./
RUN pip install --disable-pip-version-check --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels
COPY --chown=goldendict:goldendict app ./app

ENV GOLDENDICT_DICTIONARY_ROOTS=/dictionaries \
    GOLDENDICT_STARTUP_SCAN=true \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER goldendict
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-m", "app.healthcheck"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips=127.0.0.1"]
