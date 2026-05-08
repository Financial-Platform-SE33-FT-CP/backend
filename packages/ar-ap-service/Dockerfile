FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/

RUN pip install .

EXPOSE 8000

CMD ["uvicorn", "ar_ap_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
