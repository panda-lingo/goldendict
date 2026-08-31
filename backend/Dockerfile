FROM python:3.12-slim AS wheels

WORKDIR /build
COPY requirements.txt requirements-dev.txt ./
RUN pip wheel --disable-pip-version-check --no-cache-dir --wheel-dir /wheels -r requirements-dev.txt

FROM python:3.12-slim AS test
WORKDIR /work
COPY --from=wheels /wheels /wheels
COPY requirements.txt requirements-dev.txt ./
RUN pip install --disable-pip-version-check --no-cache-dir --no-index --find-links=/wheels -r requirements-dev.txt \
    && rm -rf /wheels
COPY app ./app
COPY tests ./tests
COPY pyproject.toml ./
CMD ["python", "-m", "pytest"]
