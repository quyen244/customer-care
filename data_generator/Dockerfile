FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# Landing zone is shared with Airflow (uid 50000); a fresh named volume inherits this ownership.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data/landing && chown 50000:0 /data/landing && chmod 775 /data/landing
WORKDIR /app
COPY simulator.py generate_data.py mock_crm_api.py export_loop.sh ./
USER app
EXPOSE 8000
CMD ["python", "mock_crm_api.py"]
