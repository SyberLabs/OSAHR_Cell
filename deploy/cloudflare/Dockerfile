FROM python:3.12-slim-bookworm

WORKDIR /app
COPY pyproject.toml README.md /app/
COPY osahr /app/osahr
COPY grokcell/pyproject.toml /app/grokcell/
COPY grokcell/grokcell /app/grokcell/grokcell
COPY grokcell/tests/repair_contracts /app/grokcell/tests/repair_contracts
RUN python -m pip install --no-cache-dir /app /app/grokcell

ENV PYTHONPATH=/app/grokcell:/app
ENV PYTHONDONTWRITEBYTECODE=1
EXPOSE 8080
CMD ["python", "-m", "grokcell.repair_status_http"]
