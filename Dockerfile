FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=7860

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, httpx; httpx.get(f'http://localhost:{os.environ.get(\"PORT\", \"7860\")}/health', timeout=3).raise_for_status()"

COPY start.sh .
RUN chmod +x start.sh

CMD ["./start.sh"]
