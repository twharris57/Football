# python:3.12-slim, not alpine: nfl_data_py pulls in fastparquet/cramjam, which
# frequently lack prebuilt musl wheels and force a slow/fragile Rust source
# build on alpine. Same call made in the sibling Finance-Dashboards project.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Baked in at build time so the running app can show which commit it's
# actually running (see the Streamlit footer) - verifies a deploy actually
# picked up the latest image instead of silently staying on a stale one.
ARG GIT_SHA=dev
ENV GIT_SHA=$GIT_SHA

# --create-home/--home-dir: without a real home directory, Streamlit's
# usage-stats machine-id write (~/.streamlit/...) fails at container
# startup with PermissionError, since python:3.12-slim's /home is
# root-owned and the "app" user otherwise has nowhere writable to resolve
# $HOME to.
RUN groupadd --system --gid 1000 app \
 && useradd --system --uid 1000 --gid app --create-home --home-dir /home/app app \
 && mkdir -p /app/.cache && chown -R app:app /app
ENV HOME=/home/app
USER app

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4).status==200 else 1)"

CMD ["streamlit", "run", "dynasty/streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
