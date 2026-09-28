FROM apache/airflow:slim-3.3.2-python3.12

ARG AIRFLOW_VERSION=3.3.2
ARG PYTHON_VERSION=3.12
ARG DBT_POSTGRES_VERSION=1.11.0

USER root
RUN mkdir -p /data/landing /opt/pipeline /opt/dbt-venv \
    && chown -R airflow:0 /data/landing /opt/pipeline /opt/dbt-venv
USER airflow

# Postgres provider (psycopg2) pinned by Airflow's own constraint file for this exact release.
RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" apache-airflow-providers-postgres \
      --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"

# dbt lives in its own venv: its dependency tree conflicts with Airflow's.
RUN python -m venv /opt/dbt-venv \
    && /opt/dbt-venv/bin/pip install --no-cache-dir "dbt-postgres==${DBT_POSTGRES_VERSION}"

COPY --chown=airflow:0 ingestion /opt/pipeline/ingestion
COPY --chown=airflow:0 dbt/customer_care /opt/pipeline/dbt
COPY --chown=airflow:0 airflow/dags /opt/airflow/dags

ENV PYTHONPATH=/opt/pipeline \
    DBT_PROJECT_DIR=/opt/pipeline/dbt \
    DBT_PROFILES_DIR=/opt/pipeline/dbt/profiles \
    DBT_TARGET_PATH=/tmp/dbt/target \
    DBT_LOG_PATH=/tmp/dbt/logs \
    DBT_BIN=/opt/dbt-venv/bin/dbt
