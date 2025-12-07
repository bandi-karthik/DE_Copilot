# DE_Copilot
The copilot is still in progress, an overview of it's capabilities as below

AI Powered Data Engineer Copilot on AWS, which take cares of the Data quality checks, Data Contracts, post load checks, Change detection, Historic data Test.

This application includes the following:

- Data Contracts generator: Automatic generation and application of the data contracts to ensure the data quality for the created schema.
- ETL change impact analyzer: Handles the changes in the schema or the ETL processes and notifies the Data Engineers about the lineage impact downstream, potential failures and fix suggestions.
- Data Drift Detection:  Measures the KPI parameters to identify the before and after change drift in the data to the downstream. This completely removes the core regression ETL testing on pipelines.
- Automatic Doc generator : Identifies how the table is being used and what are the other tables dependent on this, understands what kind of data is present in the table and creates a confuluence style doccument automatically.
