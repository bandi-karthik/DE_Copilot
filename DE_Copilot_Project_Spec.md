
# Project Specification: DE Copilot – AI Assistant for Data Engineers on AWS

## 0. High-Level Overview

**Goal:** Build a Data Engineer Copilot that runs on top of an AWS data lake (S3 + Glue + Athena).

For each important table / ETL pipeline, the Copilot should:

1. **Understand the table**
   - Read schema from **Glue Data Catalog**
   - Read stats from **Athena**
   - Read ETL job code (Glue PySpark) for lineage and logic

2. **Ask an LLM** (Gemini / Bedrock / etc.) to generate:
   - A **data contract** (rules the table should obey)
   - **Data quality checks** (pre-load rules + post-load tests)
   - **Markdown documentation** for the table

3. **Hook these into ETL pipelines**:
   - Pre-load checks on incoming data (before writing to curated tables)
   - Post-load tests on final tables (monitoring, alerts, drift detection)

4. **Later phases (advanced):**
   - Monitor **data drift** and anomalies over time
   - **ETL change impact analysis** (“If I change this job, what breaks?”)
   - Optional **data time machine** style analysis using stored historical stats

The stack should be AWS-native: **S3, Glue, Glue Catalog, Athena, Lambda**, plus an **LLM API**.

---

## 1. AWS Environment & Tech Stack

### 1.1 Core Components

- **Storage**
  - Raw and processed data stored in **S3**.
  - Tables defined as **Glue Catalog tables** on top of S3 paths.
  - Query engine: **Athena**.

- **ETL**
  - **Glue ETL jobs** written in PySpark.
  - Triggered by:
    - S3 event → Lambda → `StartJobRun`, or
    - Step Functions (optional later).

- **Copilot Brain**
  - **AWS Lambda** (Python) that:
    - Reads table schema from **Glue Data Catalog**.
    - Runs **Athena** queries to compute column statistics.
    - Reads ETL job script from **S3**.
    - Calls an **LLM API** (Gemini or another LLM provider).
    - Stores generated **contracts**, **tests**, and **docs** back in **S3**.

- **Optional Metadata Store**
  - **DynamoDB / RDS / S3 JSON** to keep:
    - Historical stats by date and table.
    - Test results.
    - Change history for contracts.

---

## 2. Core Concepts and Mental Model

### 2.1 Tables in the Lake

- Physically: **files in S3** (Parquet/CSV/JSON) under prefixes, e.g.:
  - `s3://my-processed-bucket/loan_repayment_fact/…`
- Logically: **Glue Catalog tables**, e.g.:
  - `analytics_db.loan_repayment_fact`
- Athena uses Glue schema + S3 files to query as if they were database tables.

### 2.2 Data Contract vs Data Quality Tests

- **Data Contract (Specification)**
  - Describes **what must be true** for a table:
    - Columns, types, nullability.
    - Primary key / grain.
    - Allowed value sets.
    - Ranges (min/max).
    - Freshness expectations (SLA).
    - Check constraints and business rules.
  - Used mainly for:
    - Designing **pre-load checks**.
    - Driving data-quality logic.

- **Data Quality Tests (Checks)**
  - Concrete validations that run at runtime:
    - **Pre-load** checks: on incoming/staging data before loading into curated tables.
    - **Post-load** checks: on final curated tables after ETL completes.
  - Implemented as:
    - SQL queries (Athena).
    - Spark expressions (Glue).
    - Configuration for frameworks (dbt tests, Great Expectations, etc.).

### 2.3 Pre-Load vs Post-Load Checks

**Pre-Load Data Quality Stage:**

- Runs **before** data is written into curated tables.
- Validates incoming files (from S3) or staging tables using contract rules:
  - Examples:
    - `contract_id > 100`
    - `emi_amount >= 0`
    - `name` not empty when not null.
    - Column type expectations, allowed values, etc.
- Bad rows → quarantined / logged.
- Good rows → proceed to ETL transformations and final write.

**Post-Load Data Quality Checks:**

- Runs **after** ETL has written to the final table.
- Validates the **curated Glue table**.
- Examples:
  - Duplicate checking on primary key / grain.
  - Null checks on non-nullable columns.
  - Range checks (min/max).
  - Foreign-key / orphan checks to dimension tables.
  - Row count anomalies versus historical average.

---

## 3. LLM Interaction Design

### 3.1 Context Object Sent to the LLM

For each table, Copilot constructs a structured **context JSON**. Example:

```json
{
  "table_name": "loan_repayment_fact",
  "database": "analytics_db",
  "layer": "curated",
  "purpose": "Fact table with one row per loan repayment (EMI).",

  "schema": [
    { "name": "loan_id", "type": "string", "nullable": false },
    { "name": "customer_id", "type": "string", "nullable": false },
    { "name": "payment_date", "type": "date", "nullable": false },
    { "name": "emi_amount", "type": "double", "nullable": false },
    { "name": "status", "type": "string", "nullable": false },
    { "name": "created_at", "type": "timestamp", "nullable": false }
  ],

  "constraints": [
    {
      "name": "ck_emi_positive",
      "type": "CHECK",
      "expression": "emi_amount >= 0"
    }
  ],

  "row_count": 125000,

  "column_stats": {
    "emi_amount": {
      "null_pct": 0.0,
      "min": 500.0,
      "max": 20000.0,
      "distinct_count": 1200,
      "p95": 15000.0
    },
    "status": {
      "null_pct": 0.0,
      "distinct_count": 3,
      "top_values": [
        { "value": "SUCCESS", "count": 110000 },
        { "value": "FAILED",  "count": 10000 },
        { "value": "PENDING", "count": 5000 }
      ]
    }
  },

  "job_summary": {
    "job_name": "loan_repayments_etl",
    "inputs": ["raw_payments", "dim_loan", "dim_customer"],
    "output": "loan_repayment_fact",
    "join_keys": [
      { "left_table": "raw_payments", "right_table": "dim_loan", "columns": ["loan_id"] },
      { "left_table": "raw_payments", "right_table": "dim_customer", "columns": ["customer_id"] }
    ],
    "filters": [
      "payment_status IN ('SUCCESS', 'FAILED', 'PENDING')"
    ],
    "grain": ["loan_id", "payment_date"]
  }
}
```

**Sources for this context:**

- `schema` → Glue Data Catalog (`get_table`).
- `row_count` & `column_stats` → Athena SQL profiling queries.
- `constraints` → DDL parsing or separate schema/contract files.
- `job_summary` → Static analysis of Glue PySpark script (from S3).

### 3.2 Expected LLM Output JSON

The LLM should return **one JSON object**, for example:

```json
{
  "data_quality": {
    "table_name": "loan_repayment_fact",
    "owner": "data-eng-team",
    "description": "Fact table with one row per loan repayment.",
    "primary_key": ["loan_id", "payment_date"],
    "freshness": {
      "frequency": "daily",
      "sla_hour_utc": 6
    },
    "columns": {
      "loan_id": {
        "type": "string",
        "nullable": false,
        "rules": [
          { "type": "not_null" },
          { "type": "foreign_key", "ref_table": "dim_loan", "ref_column": "loan_id" }
        ]
      },
      "emi_amount": {
        "type": "double",
        "nullable": false,
        "rules": [
          { "type": "not_null" },
          { "type": "min", "value": 0.0 },
          { "type": "range_soft", "min": 0.0, "max": 20000.0 }
        ]
      },
      "status": {
        "type": "string",
        "nullable": false,
        "rules": [
          { "type": "allowed_values", "values": ["SUCCESS", "FAILED", "PENDING"] }
        ]
      }
    },
    "table_level_checks": [
      {
        "type": "grain_uniqueness",
        "grain": ["loan_id", "payment_date"],
        "description": "No duplicate (loan_id, payment_date) rows."
      },
      {
        "type": "row_count_anomaly",
        "rule": "Row count should not deviate by more than 20% from a 7-day rolling average."
      }
    ]
  },

  "tests": [
    {
      "name": "pk_uniqueness_loan_id_payment_date",
      "description": "Check duplicates on grain (loan_id, payment_date).",
      "sql": "SELECT loan_id, payment_date, COUNT(*) AS cnt FROM analytics_db.loan_repayment_fact GROUP BY loan_id, payment_date HAVING cnt > 1",
      "stage": "post_load"
    },
    {
      "name": "not_null_loan_id",
      "description": "loan_id must not be null.",
      "sql": "SELECT COUNT(*) AS null_count FROM analytics_db.loan_repayment_fact WHERE loan_id IS NULL",
      "stage": "post_load"
    },
    {
      "name": "preload_emi_amount_non_negative",
      "description": "Reject rows where emi_amount < 0 before loading.",
      "rule": "emi_amount >= 0",
      "stage": "pre_load"
    }
  ],

  "docs_markdown": "# Table: loan_repayment_fact\n\n(Full human-readable documentation goes here...)"
}
```

Interpretation:

- `data_quality` = contract / rules for pre-load and conceptual DQ.
- `tests` = concrete test definitions (post-load and some explicit pre-load rules).
- `docs_markdown` = documentation to store as `.md`.

---

## 4. Implementation Phases

### Phase 0 – Local Prototype (LLM Brain Only)

**Goal:** Validate the LLM prompt and response format without any AWS dependencies.

- Hardcode a `context` dict in local Python for a simple table, e.g. `check_table`.
- Call the LLM (Gemini) with:
  - System-style instruction: “You are a senior data engineer…”
  - User content: the JSON `context` + clear instructions for output JSON format.
- Iterate until:
  - The LLM always returns valid JSON.
  - `data_quality` contains sensible rules.
  - `tests` are structured and useful.
  - `docs_markdown` is readable and consistent.

This phase focuses purely on **prompt design** and **parsing**.

---

### Phase 1 – Metadata & Stats → Contracts, Tests, Docs (AWS Integration)

**Trigger:** A Glue ETL job finishes successfully and writes/updates a table.

**Flow:**

1. **Lambda Invocation**
   - Lambda receives:
     - `database` (e.g., `"analytics_db"`),
     - `table_name` (e.g., `"loan_repayment_fact"`),
     - `job_script_s3_path` (e.g., `"s3://my-etl-code/loan_repayments_etl.py"`).

2. **Get Schema from Glue Catalog**
   - Use `boto3.client("glue").get_table` to fetch:
     - Column names and types.
     - Partition keys.
     - Table location in S3.

3. **Get Column Stats from Athena**
   - Run profiling queries via Athena:
     - Row count.
     - For each selected column:
       - `null_pct`.
       - `distinct_count`.
       - For numeric/date: `min`, `max`, maybe `p95`.
       - For categorical: `top_values` + counts.
   - Parse query results into `column_stats`.

4. **Summarize ETL Job**
   - Load the PySpark script from S3:
     - Identify input tables (e.g., `raw_payments`, `dim_loan`, `dim_customer`).
     - Identify output table (e.g., `loan_repayment_fact`).
     - Extract join keys and basic filters.
     - Infer grain if possible.

5. **Build Context JSON**
   - Assemble `context` with:
     - `table_name`, `database`, `layer`, `purpose`.
     - `schema`.
     - `constraints` (if available from DDL/metadata).
     - `row_count` and `column_stats`.
     - `job_summary`.

6. **Call LLM**
   - Send `context` and an instruction describing the expected JSON shape.
   - Receive:
     - `data_quality`.
     - `tests`.
     - `docs_markdown`.

7. **Store Outputs in S3**
   - Paths such as:
     - `s3://my-de-copilot/contracts/<table>.json`
     - `s3://my-de-copilot/tests/<table>.json`
     - `s3://my-de-copilot/docs/<table>.md`

8. **(Optional) Index in Metadata Store**
   - Store a small index row per table in DynamoDB for quick discovery.

---

### Phase 2 – Pre-Load Data Quality Engine (Contracts → Validations)

**Goal:** Use the contract rules to validate incoming data before loading into curated tables.

**Where:** Inside or alongside the Glue ETL job.

**Flow:**

1. **Load Contract**
   - At the start of the ETL, the Glue job:
     - Reads `contracts/<target_table>.json` from S3.

2. **Translate Rules to Spark Filters**
   - Map each rule type to PySpark expressions:
     - `not_null` → `col(x).isNull()`
     - `min`, `max` → `col(x) < min` or `col(x) > max`
     - `allowed_values` → `~col(x).isin(values)`
     - `check_constraint` (e.g., `contract_id > 100`) → raw expression.

3. **Apply Pre-Load Validations**
   - Compute:
     - `df_invalid` = rows that violate any rule.
     - `df_valid`  = remaining good rows.
   - Example:
     - `df_valid` is written to the normal ETL path.
     - `df_invalid` is written to a **quarantine** S3 path with extra columns (`error_reason`, `rule_name`).

4. **Emit Metrics**
   - Count invalid rows per rule.
   - Summarize in logs or metrics (e.g., CloudWatch).

---

### Phase 3 – Post-Load Data Quality Runner (Tests on Curated Tables)

**Goal:** Execute the generated tests regularly on final tables.

**Where:** Separate Glue job or Lambda that runs on a schedule.

**Flow:**

1. **Load Tests Definition**
   - Read `tests/<table>.json` from S3.

2. **Execute Tests**
   - For each test:
     - If it has `sql`: run via Athena or Spark SQL.
     - If it has a `rule`: translate into a query or filter.
   - Evaluate whether the test passes (e.g., result counts = 0 or within thresholds).

3. **Store Test Results**
   - Write results to:
     - `s3://my-de-copilot/results/<table>/<date>.json`
   - Optionally:
     - Push summary metrics to CloudWatch.
     - Trigger alerts for critical failures (e.g., SNS, Slack).

4. **Use Results for Drift/Anomaly Analysis**
   - These results feed into Phase 5 (Time Machine / Drift).

---

### Phase 4 – ETL Change Impact Analysis (“Safe Deploys”)

**Goal:** When ETL logic changes, understand and manage the impact on contracts and tests.

**Trigger:** ETL job script version changes (e.g., Git commit, changed S3 object).

**Flow:**

1. **Detect Change**
   - Compare script hash / version.
   - When new version is deployed, run impact analysis.

2. **Load Old and New Contexts**
   - Old context: from historical metadata.
   - New context: recompute via Glue + Athena + new job script.

3. **Use LLM for Impact Description**
   - Ask:
     - What changed?
     - Which columns/rules may be affected?
     - Which tests are now suspicious or obsolete?
   - Generate suggestions:
     - New rules.
     - Updated tests.
     - Potentially impacted downstream tables.

4. **Present as a Report**
   - Markdown report stored in S3 or a dashboard.
   - Optional: propose specific edits to contracts and tests.

5. **Optional Shadow-Run**
   - Run old and new ETL in parallel on a sample.
   - Compare outputs and stats.
   - Use LLM to summarize differences.

---

### Phase 5 – Time Machine & Drift / Anomaly Insight (Optional Extension)

**Goal:** Use historical profiles and test results to understand long-term changes.

**Data Collected Daily:**

- Row counts.
- Min/max/p95 for numeric columns.
- Distinct counts / category distribution for key columns.
- Test pass/fail counts and failure reasons.

**Storage:**

- `s3://my-de-copilot/stats-history/<table>/<date>.json`
- Or a DynamoDB table keyed by `(table_name, date)`.

**LLM Usage:**

- Given a time series of stats and test results:
  - Highlight anomalies (e.g., row count jumped 50%).
  - Explain possible reasons.
  - Suggest new or adjusted rules and thresholds.

---

## 5. Handling Special Scenarios

### 5.1 Brand-New Target Table (No Data Yet)

- Use a **contract-first** YAML/JSON spec for the table:
  - Columns, types, grain, basic rules.
- LLM generates:
  - Initial contract.
  - Initial tests.
  - Documentation.
- After the first successful ETL run:
  - Add real stats from Athena to refine the contract and tests.

### 5.2 Existing Dimension / Reference Tables

- Tables like `dim_customer`, `dim_loan`:
  - Already exist in Glue/S3.
- Copilot:
  - Generates contracts and tests for them too.
  - Uses them for foreign key checks in fact tables.

---

## 6. File Layout and Conventions

Suggested S3 layout for Copilot artifacts:

- Contracts:
  - `s3://my-de-copilot/contracts/<table>.json`
- Tests:
  - `s3://my-de-copilot/tests/<table>.json`
- Documentation:
  - `s3://my-de-copilot/docs/<table>.md`
- Test results:
  - `s3://my-de-copilot/results/<table>/<date>.json`
- Historical stats:
  - `s3://my-de-copilot/stats-history/<table>/<date>.json`

Each ETL job knows its **target table name**, so it can look up:

- `contracts/<target_table>.json` for pre-load rules.
- `tests/<target_table>.json` for the DQ runner.

---

## 7. What I Want Help With (From the LLM)

Given this entire spec, I want the LLM (Gemini) to help me:

1. Implement the **Phase 0 local prototype**:
   - Hard-coded `context` in Python.
   - A robust prompt for generating `data_quality`, `tests`, `docs_markdown`.
   - JSON parsing and validation of the LLM response.

2. Implement **AWS integration** (Phase 1):
   - Functions to:
     - Read schema from Glue Catalog.
     - Compute column stats using Athena.
     - Summarize the Glue PySpark job.
     - Build the `context` JSON and call the LLM.

3. Implement **pre-load and post-load engines** (Phases 2 & 3):
   - Code that:
     - Reads `contracts/<table>.json` and converts rules → Spark filters.
     - Reads `tests/<table>.json` and runs them via Athena/Spark.
     - Stores results, metrics, and logs properly.

4. Incrementally add:
   - ETL change impact analysis (Phase 4).
   - Time machine / drift insights (Phase 5).

This document is the full specification of the **DE Copilot** project I want to build.
