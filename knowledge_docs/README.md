# Knowledge-base documents

Put the documentation used by the **Knowledge Agent** here (user guides, FAQs,
business rules, screenshots, training videos). Supported formats:
PDF, DOCX, PPTX, XLSX, PNG and MP4.

The files in this folder are **git-ignored**: they are uploaded to the Snowflake
stage `@HYPERCARE_DB.PUBLIC.DOCS` and indexed by `sql/02_kb_builder.sql`.

## Upload to Snowflake

**Snowsight:** *Data → Databases → HYPERCARE_DB → PUBLIC → Stages → DOCS → + Files*

**Snowflake CLI:**

```bash
snow stage copy "knowledge_docs/*" @HYPERCARE_DB.PUBLIC.DOCS --overwrite
```

**SnowSQL / worksheet with PUT:**

```sql
PUT file://knowledge_docs/* @HYPERCARE_DB.PUBLIC.DOCS AUTO_COMPRESS = FALSE OVERWRITE = TRUE;
ALTER STAGE HYPERCARE_DB.PUBLIC.DOCS REFRESH;
```

Then run `sql/02_kb_builder.sql` to (re)build the Cortex Search service.
