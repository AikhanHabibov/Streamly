FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DATA_DIR=/data
WORKDIR /srv/streamnest
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 streamnest \
    && mkdir -p /data/media && chown -R streamnest:streamnest /data
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY --chown=streamnest:streamnest app ./app
USER streamnest
EXPOSE 8000
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--workers","2","--proxy-headers","--forwarded-allow-ips=*","--no-access-log"]
