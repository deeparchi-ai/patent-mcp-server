FROM python:3.11-slim

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml .
COPY src/ ./src/
RUN pip install --no-cache-dir .

CMD ["python", "src/server.py", "--transport", "http", "--port", "8080"]
