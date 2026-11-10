-- ============================================================
-- Maritime Hypercare Agents — Snowflake environment setup
-- Run once in a Snowsight SQL worksheet, BEFORE 01_seed_data.sql.
--
-- To use other names, change them here AND in 01/02 (top USE statements)
-- and in the app config (HYPERCARE_DATABASE / HYPERCARE_SCHEMA env vars,
-- app/snowflake.yml).
-- ============================================================

USE ROLE ACCOUNTADMIN;  -- or any role allowed to create databases & use Cortex

-- Warehouse used by the seed scripts, Cortex Search and the Streamlit app
CREATE WAREHOUSE IF NOT EXISTS COMPUTE_WH
    WAREHOUSE_SIZE = 'XSMALL'
    AUTO_SUSPEND = 60
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE;

CREATE DATABASE IF NOT EXISTS HYPERCARE_DB;
CREATE SCHEMA IF NOT EXISTS HYPERCARE_DB.PUBLIC;

USE DATABASE HYPERCARE_DB;
USE SCHEMA PUBLIC;
USE WAREHOUSE COMPUTE_WH;

-- Internal stage holding the knowledge-base documents (PDF, DOCX, PPTX, XLSX, PNG, MP4).
-- Server-side encryption + directory table are required by AI_PARSE_DOCUMENT / AI_TRANSCRIBE.
CREATE STAGE IF NOT EXISTS DOCS
    DIRECTORY = (ENABLE = TRUE)
    ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE');

-- Optional (account-level): allow Cortex models to be called from any region
-- (e.g. when the chosen model is not available in your region).
-- ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'ANY_REGION';

-- Next steps:
--   1. Upload your documents to @HYPERCARE_DB.PUBLIC.DOCS
--      (Snowsight: Data > Databases > HYPERCARE_DB > PUBLIC > Stages > DOCS > + Files,
--       or: PUT file://knowledge_docs/* @HYPERCARE_DB.PUBLIC.DOCS AUTO_COMPRESS=FALSE;)
--   2. ALTER STAGE DOCS REFRESH;
--   3. Run 01_seed_data.sql, then 02_kb_builder.sql
