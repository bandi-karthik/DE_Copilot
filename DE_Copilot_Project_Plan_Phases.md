
# DE Copilot on AWS – 4-Phase Project Plan

Author: (You)
Date: (Fill in)

---

## Overview

This document describes a practical, multi-phase project to build an **AI-powered Data Engineer Copilot on AWS**.  
The Copilot helps data engineers by:

- Generating **data quality checks, data contracts, and documentation** for new/changed tables.
- Maintaining a **lineage graph** of jobs, tables, and dashboards.
- Performing **impact analysis** when ETL/logic changes.
- (Later) Simulating **KPI impact over historical data** – a “Data Time Machine”.

All phases are designed to be buildable step-by-step and demoable individually.

---

## Common Tech Stack (All Phases)

- **AWS S3** – data lake + configs + Copilot outputs
- **AWS Glue** – ETL jobs (PySpark) + Data Catalog (schemas)
- **AWS Athena** – querying tables and computing column stats
- **AWS Lambda** – runs the Copilot logic (orchestrator + LLM calls)
- **Amazon Bedrock (or other LLM API)** – large language model for suggestions/explanations
- (Optional later) **DynamoDB** – store lineage & metadata
- (Optional later) **EventBridge / CodeCommit / GitHub** – triggers on changes

---

## Phase 1 – Core DE Copilot (DQ + Contract + Docs)

### Goal

Given a table produced by an ETL job, automatically:

- Inspect its **schema** and **basic column stats**.
- Understand how it was **produced** (inputs, joins, grain) from the ETL code.
- Use an LLM to generate:
  - Suggested **data quality tests** (not-null, uniqueness, ranges, FK checks, anomaly-style checks).
  - A **data contract** (keys, expectations, freshness).
  - Human-readable **documentation** for the table.

Output is stored as YAML/JSON + Markdown in S3 for engineers to review and use.

### AWS Components

- **S3**
  - `my-raw-bucket` – raw data
  - `my-processed-bucket` – curated/processed data
  - `de-copilot-output-bucket` – Copilot outputs (tests/docs)
- **Glue**
  - Glue ETL jobs (PySpark) writing tables to S3
  - Glue Data Catalog database, e.g. `analytics_db`
- **Athena**
  - Configured to query `analytics_db` tables
- **Lambda**
  - Function: `de_copilot_analyze_table`
- **Bedrock**
  - LLM model endpoint (e.g., Claude / LLaMA / Titan)

### Input (to Lambda)

```json
{
  "glue_database": "analytics_db",
  "table_name": "customer_positions_daily",
  "job_script_s3_path": "s3://my-etl-code/positions_job.py"
}
```

### Internal Steps

1. **Fetch schema**
   - Use Glue Data Catalog via `boto3.glue.get_table` to get column names + types.

2. **Fetch basic stats**
   - Use Athena to run queries on the target table:
     - Row count
     - Null counts
     - Distinct counts
     - Min/max for numeric/date columns
   - Build a `column_stats` dict.

3. **Read ETL job code**
   - Read PySpark/SQL script from S3.
   - Parse (even with simple regex) for:
     - Input tables (reads_from)
     - Output table
     - Join keys / filters.

4. **Build LLM context**
   - JSON object summarizing:
     - `table_name`
     - `schema`
     - `column_stats`
     - `job_summary` (inputs, output, join_keys, grain if known)

5. **Call LLM (Bedrock)**
   - Prompt: “You are a senior data engineer…”
   - Ask for JSON with:
     - `"tests"` – a list of test definitions
     - `"contract"` – primary keys, column rules, freshness expectations
     - `"docs_markdown"` – description of the table

6. **Write outputs to S3**
   - Convert `tests` → YAML/JSON (dbt / Great Expectations style).
   - Save:
     - `s3://de-copilot-output-bucket/tests/<table_name>.yaml`
     - `s3://de-copilot-output-bucket/docs/<table_name>.md`

### What You Learn in Phase 1

- Using Glue Catalog + Athena programmatically via `boto3`.
- Computing lightweight column stats at scale.
- Building structured LLM prompts using real metadata.
- Parsing LLM JSON responses and turning them into usable configs/docs.
- Packaging logic in AWS Lambda.

---

## Phase 2 – Lineage Graph (Jobs ↔ Tables ↔ Dashboards)

### Goal

Maintain a **simple lineage graph** that records:

- Which jobs **read** which tables.
- Which jobs **write** which tables.
- Which dashboards/reports **depend** on which tables.

This is the foundation for impact analysis and KPI simulation later.

### AWS Components

- **Same as Phase 1**, plus:
  - **DynamoDB** or S3 JSON as a metadata/lineage store.

### Data Model for Lineage (Example)

Each time `de_copilot_analyze_table` runs, it stores lineage like:

```json
{
  "object_type": "JOB",
  "object_name": "positions_job",
  "reads_from": ["raw_positions", "dim_customer"],
  "writes_to": ["customer_positions_daily"]
}
```

And for tables:

```json
{
  "object_type": "TABLE",
  "object_name": "customer_positions_daily",
  "written_by": ["positions_job"],
  "read_by": ["risk_report_job"]
}
```

For dashboards/reports (initially via static config in S3):

```json
[
  {
    "dashboard_name": "Daily Risk Dashboard",
    "tables_used": ["customer_positions_daily", "risk_scores_daily"]
  },
  {
    "dashboard_name": "Positions by Product Category",
    "tables_used": ["customer_positions_daily", "dim_product"]
  }
]
```

### Internal Steps

1. Extend Phase 1 Lambda:
   - After parsing ETL script, store:
     - Job → input tables
     - Job → output tables
   - Write/update lineage records in DynamoDB or S3.

2. Add a small helper function:
   - Given a `table_name`, find:
     - Jobs that write it.
     - Jobs that read it.
     - Dashboards that depend on it.

### What You Learn in Phase 2

- Designing and maintaining simple metadata/lineage structures.
- Understanding data dependencies across ETL jobs and marts.
- Building the foundation for impact analysis.

---

## Phase 3 – Impact Analyzer (Change Guardian)

### Goal

When an ETL job or table changes, automatically:

- Detect what changed (schema, logic, inputs).
- Use the lineage graph to identify:
  - All **downstream jobs**.
  - All **downstream tables**.
  - All **affected dashboards/reports**.
- Generate a **human-readable impact report** (with help from LLM).

### AWS Components

- **Lambda**
  - Function: `de_copilot_impact_analyzer`
- **DynamoDB / S3 JSON**
  - Stores current & previous versions of job/table metadata.
- **Bedrock**
  - To generate readable impact summaries.

### Input (to impact analyzer)

Example:

```json
{
  "job_name": "product_dim_job"
}
```

### Internal Steps

1. **Fetch latest job metadata**
   - From lineage + current ETL code.
2. **Fetch previous metadata**
   - From stored “last analyzed” snapshot in S3/DynamoDB.
3. **Compute diff**
   - New/removed input tables.
   - New/removed columns in output tables.
   - Changed filters/conditions (where possible).
4. **Find downstream dependencies**
   - Jobs reading affected tables.
   - Dashboards using those tables.
5. **Generate impact summary (LLM)**
   - Prompt LLM with:
     - The diff.
     - List of downstream jobs/dashboards.
   - Ask it to write:
     - A short impact report.
     - Severity (low/medium/high).
6. **Output**
   - JSON:
     - `impacted_jobs`, `impacted_tables`, `impacted_dashboards`.
   - Markdown report in:
     - `s3://de-copilot-output-bucket/impact_reports/<job_name>_<timestamp>.md`

### Examples of Detected Changes

- Column removed:
  - `product_group` removed from `dim_product`:
    - Downstream job `positions_fact_job` uses it → risk: HIGH.
- New category/value:
  - New status value `"CRYPTO"` appears → might require dashboard update.

### What You Learn in Phase 3

- Versioning of metadata & computing diffs.
- Traversing a dependency graph to compute blast radius.
- Using LLMs to turn technical diffs into business-friendly explanations.

---

## Phase 4 – Data Time Machine (KPI Impact Simulation)

### Goal

For key **business KPIs**, simulate how they would have changed over historical data if:

- A new ETL logic had been applied, or
- A table’s definition changed.

This is a “Data Time Machine” that helps answer:

> “If we change this logic today, what would our last 30–90 days of metrics have looked like?”

### AWS Components

- **Athena**
  - To run old vs new logic over historical partitions.
- **Lambda**
  - Function: `de_copilot_kpi_simulator`
- **Bedrock**
  - To summarize KPI differences.

### KPI Config Example

Store in S3:

```json
[
  {
    "kpi_name": "Total AUM",
    "sql": "SELECT as_of_date, SUM(market_value) AS total_aum FROM customer_positions_daily GROUP BY as_of_date",
    "depends_on_tables": ["customer_positions_daily"]
  },
  {
    "kpi_name": "Active Customers",
    "sql": "SELECT as_of_date, COUNT(DISTINCT customer_id) AS active_customers FROM customer_positions_daily WHERE market_value > 0 GROUP BY as_of_date",
    "depends_on_tables": ["customer_positions_daily"]
  }
]
```

### Internal Steps

1. **Identify affected KPIs**
   - From impact analysis:
     - If `customer_positions_daily` changes, find all KPIs that depend on it.
2. **Compute KPI history (old vs new)**
   - Use Athena:
     - Run the KPI SQL using **old logic** (or old table definition) over N days (if still accessible).  
     - Run the KPI SQL using **new logic** over the same window.
3. **Compare**
   - Day-by-day differences:
     - Absolute difference.
     - Percentage difference.
4. **Generate explanation (LLM)**
   - Prompt:
     - Provide before/after KPI series.
   - Ask LLM:
     - “Explain how KPIs would change and why (based on table change description).”
5. **Output**
   - JSON with KPI deltas.
   - Markdown “KPI impact report”.

### What You Learn in Phase 4

- Backfilling / historical recomputation concepts.
- KPI modeling and dependency tracking.
- Combining technical changes + business metrics + LLM summaries.

---

## Suggested Build Order

1. **Phase 1 – Core Copilot**
   - Local Python script → then AWS Lambda.
   - Single table → single job → tests + contract + docs output.

2. **Phase 2 – Lineage Graph**
   - Add lineage recording inside Phase 1 Lambda.
   - Store lineage in S3 JSON or DynamoDB.

3. **Phase 3 – Impact Analyzer**
   - Build a separate Lambda.
   - Use lineage + metadata diffs to compute affected jobs/tables/dashboards.
   - Use LLM to generate impact reports.

4. **Phase 4 – Data Time Machine**
   - Start with 1–2 KPIs.
   - Implement old vs new KPI SQL comparison for a 30-day window.
   - Add LLM summaries.

Each phase is independently demoable and adds concrete value for data engineers.

---

## How to Pitch This Project (Short Version)

> “I built an AI-powered DE Copilot on AWS that:
> - Analyzes Glue ETL jobs and their tables to auto-generate data-quality tests, data contracts, and documentation using an LLM.
> - Maintains lineage between jobs, tables, and dashboards.
> - Runs impact analysis when ETL or schema changes happen, showing which downstream jobs and reports are at risk.
> - (Optionally) simulates how key business KPIs would have changed historically if new logic had been applied — a ‘Data Time Machine’.
> 
> It’s built on S3, Glue, Athena, Lambda, and Bedrock, and is designed to reduce manual DQ work and make pipeline changes safer and more transparent for data engineers.”

You can now expand or trim this doc depending on whether it’s for:
- README / GitHub
- Resume
- Project proposal / presentation
