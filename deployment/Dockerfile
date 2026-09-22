FROM python:3.11.15-slim
WORKDIR /app
COPY deployment/requirements/service.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock \
    && useradd --uid 10001 --create-home asr \
    && mkdir /data && chown asr:asr /data
COPY src/asr_service /app/asr_service
USER asr
ENV PYTHONUNBUFFERED=1
EXPOSE 8090
CMD ["python", "-m", "asr_service", "api", "--host", "0.0.0.0", "--port", "8090"]
