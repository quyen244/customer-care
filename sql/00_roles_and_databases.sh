#!/bin/sh
# Runs once on first Postgres start. Creates least-privilege roles and one database per app.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
  CREATE ROLE etl_user   LOGIN PASSWORD '${ETL_DB_PASSWORD}';
  CREATE ROLE bi_reader  LOGIN PASSWORD '${BI_DB_PASSWORD}';
  CREATE ROLE alerting_bot LOGIN PASSWORD '${ALERTING_DB_PASSWORD}';
  CREATE ROLE airflow    LOGIN PASSWORD '${AIRFLOW_DB_PASSWORD}';
  CREATE ROLE n8n        LOGIN PASSWORD '${N8N_DB_PASSWORD}';
  CREATE ROLE metabase   LOGIN PASSWORD '${METABASE_DB_PASSWORD}';

  CREATE DATABASE airflow  OWNER airflow;
  CREATE DATABASE n8n      OWNER n8n;
  CREATE DATABASE metabase OWNER metabase;

  REVOKE ALL ON DATABASE ${POSTGRES_DB} FROM PUBLIC;
  GRANT CONNECT, TEMP ON DATABASE ${POSTGRES_DB} TO etl_user;
  GRANT CREATE ON DATABASE ${POSTGRES_DB} TO etl_user;
  GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO bi_reader, alerting_bot;
SQL
