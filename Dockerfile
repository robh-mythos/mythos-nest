FROM python:3.11-slim

# system deps for pdf2image (poppler) and OCR (tesseract)
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils tesseract-ocr \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt

# gunicorn serves FastAPI
CMD ["gunicorn", "nest_service:app", "-w", "2", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:8080"]
