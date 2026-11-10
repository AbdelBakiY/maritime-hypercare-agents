-- ============================================================
-- Maritime Hypercare Agents — Knowledge base builder
-- Parses documents, chunks text and creates the Cortex Search service.
-- Prerequisite: documents uploaded to the @DOCS stage (see 00_setup.sql).
-- ============================================================

USE ROLE ACCOUNTADMIN;
USE DATABASE HYPERCARE_DB;
USE SCHEMA PUBLIC;
USE WAREHOUSE COMPUTE_WH;

-- ============================================================
-- Step 1: Parse Documents (PDF, DOCX, PPTX, XLSX)
-- ============================================================

ALTER STAGE DOCS REFRESH;

CREATE OR REPLACE TABLE RAW_TEXT AS
SELECT
    RELATIVE_PATH,
    SPLIT_PART(RELATIVE_PATH, '.', -1) AS file_type,
    TO_VARCHAR(
        AI_PARSE_DOCUMENT(
            TO_FILE('@DOCS', RELATIVE_PATH),
            {'mode': 'LAYOUT'}
        ):content
    ) AS EXTRACTED_LAYOUT
FROM
    DIRECTORY('@DOCS')
WHERE
    RELATIVE_PATH NOT LIKE '%.mp4'
    AND RELATIVE_PATH NOT LIKE '%.png';

-- ============================================================
-- Step 2: Parse Images (PNG)
-- ============================================================

CREATE OR REPLACE TEMPORARY TABLE RAW_TEXT_IMAGES AS
SELECT
    RELATIVE_PATH,
    'png' AS file_type,
    TO_VARCHAR(
        AI_PARSE_DOCUMENT(
            TO_FILE('@DOCS', RELATIVE_PATH),
            {'mode': 'LAYOUT'}
        ):content
    ) AS EXTRACTED_LAYOUT
FROM
    DIRECTORY('@DOCS')
WHERE
    RELATIVE_PATH LIKE '%.png';

-- ============================================================
-- Step 3: Transcribe Videos (MP4)
-- ============================================================

CREATE OR REPLACE TEMPORARY TABLE RAW_TEXT_VIDEOS AS
SELECT
    RELATIVE_PATH,
    'mp4' AS file_type,
    AI_TRANSCRIBE(
        TO_FILE('@DOCS', RELATIVE_PATH)
    ):text::VARCHAR AS EXTRACTED_LAYOUT
FROM
    DIRECTORY('@DOCS')
WHERE
    RELATIVE_PATH LIKE '%.mp4';

-- ============================================================
-- Step 4: Merge All Sources
-- ============================================================

CREATE OR REPLACE TEMPORARY TABLE RAW_TEXT_MERGED AS
SELECT RELATIVE_PATH, file_type, EXTRACTED_LAYOUT FROM RAW_TEXT
UNION ALL
SELECT RELATIVE_PATH, file_type, EXTRACTED_LAYOUT FROM RAW_TEXT_IMAGES
UNION ALL
SELECT RELATIVE_PATH, file_type, EXTRACTED_LAYOUT FROM RAW_TEXT_VIDEOS;

CREATE OR REPLACE TABLE RAW_TEXT AS
SELECT * FROM RAW_TEXT_MERGED;

-- ============================================================
-- Step 5: Chunk Text
-- ============================================================

CREATE OR REPLACE TABLE DOC_CHUNKS AS
SELECT
    relative_path,
    file_type,
    BUILD_SCOPED_FILE_URL('@DOCS', relative_path) AS file_url,
    (
        relative_path || ':\n'
        || COALESCE('Header 1: ' || c.value['headers']['header_1'] || '\n', '')
        || COALESCE('Header 2: ' || c.value['headers']['header_2'] || '\n', '')
        || c.value['chunk']
    ) AS chunk,
    c.value['headers']['header_1']::VARCHAR AS header_1,
    c.value['headers']['header_2']::VARCHAR AS header_2
FROM
    RAW_TEXT,
    LATERAL FLATTEN(SNOWFLAKE.CORTEX.SPLIT_TEXT_MARKDOWN_HEADER(
        EXTRACTED_LAYOUT,
        OBJECT_CONSTRUCT('#', 'header_1', '##', 'header_2'),
        2000,
        300
    )) c
WHERE EXTRACTED_LAYOUT IS NOT NULL AND LENGTH(EXTRACTED_LAYOUT) > 0;

-- ============================================================
-- Step 6: Create Cortex Search Service
-- ============================================================

CREATE OR REPLACE CORTEX SEARCH SERVICE KNOWLEDGE_BASE
    ON chunk
    ATTRIBUTES file_type
    WAREHOUSE = COMPUTE_WH
    TARGET_LAG = '1 hour'
    AS (
        SELECT
            chunk,
            relative_path,
            file_url,
            file_type,
            header_1,
            header_2
        FROM DOC_CHUNKS
    );
