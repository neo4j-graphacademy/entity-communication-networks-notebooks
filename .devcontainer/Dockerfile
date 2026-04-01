FROM mcr.microsoft.com/devcontainers/python:3.11

# Install tesseract for OCR notebooks (1.2, 1.3)
RUN apt-get update && apt-get install -y tesseract-ocr && rm -rf /var/lib/apt/lists/*
