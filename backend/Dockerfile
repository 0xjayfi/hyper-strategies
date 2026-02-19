FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src/ src/
COPY backend/ backend/
COPY data/ data/
COPY .env* ./

RUN pip install --no-cache-dir -e ".[backend]"

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
