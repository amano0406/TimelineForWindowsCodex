FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY worker/pyproject.toml /app/worker/pyproject.toml
COPY worker/src /app/worker/src
RUN pip install --no-cache-dir -e /app/worker

COPY configs/ /app/config/

ENV PYTHONPATH=/app/worker/src
ENV TIMELINE_FOR_WINDOWS_CODEX_RUNTIME=docker
ENTRYPOINT ["python", "-m", "timeline_for_windows_codex_worker"]
CMD ["items", "refresh"]
