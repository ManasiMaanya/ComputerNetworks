FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY web/ web/
COPY data/samples/ data/samples/
COPY configs/ configs/

ENV PYTHONPATH=/app
EXPOSE 8765

CMD ["python", "-m", "uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8765"]
