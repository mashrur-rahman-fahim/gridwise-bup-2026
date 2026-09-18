FROM python:3.11-slim

# CBC ships inside the pulp wheel; no apt packages are required.
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY samples/ ./samples/

# No secrets are baked into this image. GEMINI_API_KEY must be supplied at run
# time with -e. The service still starts and serves valid schedules without it,
# interpreting every note as no_op.
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
