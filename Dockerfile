# Backend image: API, Celery worker, Celery beat and the one-off init job all run from this.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY dealradar ./dealradar
COPY retailers ./retailers
RUN pip install .

RUN useradd --system --uid 10001 dealradar
USER dealradar

EXPOSE 8000
CMD ["uvicorn", "dealradar.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
