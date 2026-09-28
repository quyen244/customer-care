-- Warehouse layout. raw + data_quality are written by Python ingestion;
-- staging + marts are created and owned by dbt (etl_user).
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

CREATE SCHEMA raw          AUTHORIZATION etl_user;
CREATE SCHEMA data_quality AUTHORIZATION etl_user;
CREATE SCHEMA staging      AUTHORIZATION etl_user;
CREATE SCHEMA marts        AUTHORIZATION etl_user;

SET ROLE etl_user;

-- ---------------------------------------------------------------- raw layer
-- One table per source entity, upserted on the natural key. Values are stored as delivered
-- (e.g. status casing untouched); only type coercion happens before load.

CREATE TABLE raw.crm_customers (
    customer_id      text PRIMARY KEY,
    company_name     text NOT NULL,
    contact_name     text,
    email            text,
    phone            text,
    segment          text,
    industry         text,
    region           text,
    country          text,
    plan_tier        text,
    billing_cycle    text,
    account_manager  text,
    signup_date      date,
    is_active        boolean,
    churn_date       date,
    updated_at       timestamptz NOT NULL,
    _batch_id        uuid NOT NULL,
    _source          text NOT NULL,
    _loaded_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE raw.agents (
    agent_id         text PRIMARY KEY,
    agent_name       text NOT NULL,
    email            text,
    team             text,
    shift            text,
    hire_date        date,
    termination_date date,
    is_active        boolean,
    updated_at       timestamptz NOT NULL,
    _batch_id        uuid NOT NULL,
    _source          text NOT NULL,
    _loaded_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE raw.tickets (
    ticket_id          text PRIMARY KEY,
    customer_id        text NOT NULL,
    agent_id           text,
    subject            text,
    category           text,
    subcategory        text,
    priority           text NOT NULL,
    channel            text,
    status             text NOT NULL,
    created_at         timestamptz NOT NULL,
    first_response_at  timestamptz,
    resolved_at        timestamptz,
    closed_at          timestamptz,
    reopened_at        timestamptz,
    reopen_count       integer NOT NULL DEFAULT 0,
    updated_at         timestamptz NOT NULL,
    _batch_id          uuid NOT NULL,
    _source            text NOT NULL,
    _loaded_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_raw_tickets_loaded_at ON raw.tickets (_loaded_at);

CREATE TABLE raw.sales_orders (
    order_id       text PRIMARY KEY,
    customer_id    text NOT NULL,
    order_date     date NOT NULL,
    plan           text,
    order_type     text,
    billing_cycle  text,
    amount         numeric(12, 2) NOT NULL,
    currency       text,
    status         text,
    sales_rep      text,
    updated_at     timestamptz NOT NULL,
    _batch_id      uuid NOT NULL,
    _source        text NOT NULL,
    _loaded_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE raw.csat_surveys (
    survey_id     text PRIMARY KEY,
    ticket_id     text NOT NULL,
    customer_id   text,
    sent_at       timestamptz NOT NULL,
    responded_at  timestamptz,
    score         smallint,
    comment       text,
    updated_at    timestamptz NOT NULL,
    _batch_id     uuid NOT NULL,
    _source       text NOT NULL,
    _loaded_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_raw_csat_loaded_at ON raw.csat_surveys (_loaded_at);

-- ---------------------------------------------------------------- data quality / ops
CREATE TABLE data_quality.ingestion_runs (
    run_id         bigserial PRIMARY KEY,
    batch_id       uuid NOT NULL,
    source         text NOT NULL,
    source_file    text,
    started_at     timestamptz NOT NULL,
    finished_at    timestamptz,
    status         text NOT NULL CHECK (status IN ('running', 'success', 'failed', 'skipped')),
    rows_read      integer NOT NULL DEFAULT 0,
    rows_loaded    integer NOT NULL DEFAULT 0,
    rows_rejected  integer NOT NULL DEFAULT 0,
    rows_duplicate integer NOT NULL DEFAULT 0,
    error          text
);
CREATE INDEX ix_ingestion_runs_started ON data_quality.ingestion_runs (started_at DESC);

CREATE TABLE data_quality.rejected_records (
    id           bigserial PRIMARY KEY,
    batch_id     uuid NOT NULL,
    source       text NOT NULL,
    source_file  text,
    record_key   text,
    reason       text NOT NULL,
    detail       text,
    raw_record   jsonb NOT NULL,
    rejected_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_rejected_source_reason ON data_quality.rejected_records (source, reason);

-- File-level idempotency: a file with the same name + checksum is never loaded twice.
CREATE TABLE data_quality.ingested_files (
    source       text NOT NULL,
    file_name    text NOT NULL,
    sha256       text NOT NULL,
    batch_id     uuid NOT NULL,
    ingested_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, file_name)
);

-- API-level incrementality: last updated_at successfully loaded per API source.
CREATE TABLE data_quality.source_watermarks (
    source      text PRIMARY KEY,
    watermark   timestamptz NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

RESET ROLE;

-- ---------------------------------------------------------------- alerting (written by n8n)
CREATE SCHEMA alerting AUTHORIZATION etl_user;
CREATE TABLE alerting.alert_log (
    id          bigserial PRIMARY KEY,
    alert_type  text NOT NULL CHECK (alert_type IN ('sla_compliance', 'backlog', 'urgent_breach', 'pipeline_failure')),
    alert_key   text NOT NULL,
    severity    text NOT NULL CHECK (severity IN ('critical', 'warning')),
    message     text NOT NULL,
    metrics     jsonb,
    channels    text[] NOT NULL,
    sent_at     timestamptz NOT NULL DEFAULT now()
);
-- Dedup lookups: "was this urgent ticket already alerted?", "when did this condition last fire?"
CREATE INDEX ix_alert_log_type_key ON alerting.alert_log (alert_type, alert_key, sent_at DESC);
ALTER TABLE alerting.alert_log OWNER TO etl_user;

-- ---------------------------------------------------------------- read access
GRANT USAGE ON SCHEMA marts, data_quality, alerting TO bi_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA data_quality, alerting TO bi_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE etl_user IN SCHEMA marts GRANT SELECT ON TABLES TO bi_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE etl_user IN SCHEMA data_quality GRANT SELECT ON TABLES TO bi_reader;

GRANT USAGE ON SCHEMA marts, alerting TO alerting_bot;
ALTER DEFAULT PRIVILEGES FOR ROLE etl_user IN SCHEMA marts GRANT SELECT ON TABLES TO alerting_bot;
GRANT SELECT, INSERT ON alerting.alert_log TO alerting_bot;
GRANT USAGE ON SEQUENCE alerting.alert_log_id_seq TO alerting_bot;
