## Flow 

1. local LLM call testing done with the mock up ddl json to get the data quality checks and the test cases, refer @DE_Copilot/prototype/pt2.ipynb. 
2. created S3 bucket and created roles such as athena, glue , S3, cloudwatchevents, cloudwatchlogs such that lambda can access them.
3. created a dummy database and a dummy table employees_test inside it with some few columns.
4. used boto3 to connect to the glue, athena , to get the statistics, metadata, columnar information for each tables and parse them to the LLM to get the json output.
5. placed the LMM generated output json in the s3 bucket, so that it can be used by the glue job.