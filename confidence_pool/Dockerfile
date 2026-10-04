# Not alpine: fastparquet/cramjam (via nfl_data_py) lack musl wheels.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Shown in the app footer to confirm a deploy picked up the new image.
ARG GIT_SHA=dev
ENV GIT_SHA=$GIT_SHA

# Streamlit writes ~/.streamlit at startup, so the user needs a writable home.
RUN groupadd --system --gid 1000 app \
 && useradd --system --uid 1000 --gid app --create-home --home-dir /home/app app \
 && mkdir -p /app/confidence_pool_data && chown -R app:app /app
ENV HOME=/home/app
USER app

EXPOSE 8502

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8502/_stcore/health', timeout=4).status==200 else 1)"

CMD ["streamlit", "run", "confidence_pool/streamlit_app.py", "--server.port=8502", "--server.address=0.0.0.0", "--server.headless=true"]
