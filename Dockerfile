FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt requirements-ml.txt ./
ARG INSTALL_ML=true
RUN pip install -r requirements.txt \
    && if [ "$INSTALL_ML" = "true" ]; then pip install -r requirements-ml.txt; fi

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY config ./config
COPY data ./data

RUN useradd --create-home --uid 1000 helpdesk
USER helpdesk

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

CMD ["sh", "-c", "alembic upgrade head && python -m app.seed --if-empty && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
