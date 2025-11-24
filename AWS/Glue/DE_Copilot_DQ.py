import sys, json
import boto3
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
import pyspark
import pyspark.sql.functions as f


## @params: [JOB_NAME]
args = getResolvedOptions(sys.argv, ['JOB_NAME'])

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)
database = 'copilot_demo'
bucket = 'de-copilot-s3'
table = 'employees_test'
key = f'contracts/{table}.json'
input_path = 's3://de-copilot-s3/data/incoming/employees_test.csv'
valid_records_output = f's3://de-copilot-s3/data/processed/{table}/'
invalid_records_output = f's3://de-copilot-s3/data/error/{table}_error/'

def dq_rules(bucket,table,key):

    
    # Read the incoming file 
        
    df = spark.read.option('header','true').option('inferschema','false').csv(input_path)
    
    # data type checks 
    
    dtypes_check = {}
    dtype_rules = []
    
    glue_client = boto3.client('glue')
    cur_tab = glue_client.get_table(DatabaseName=database,Name=table)
    for col in cur_tab['Table']['StorageDescriptor']['Columns']:
        dtypes_check[col['Name']] = col['Type']
    for col in cur_tab['Table'].get("PartitionKeys", []):
        dtypes_check[col['Name']] = col['Type']
    
    for col,target_type in dtypes_check.items():
        if not target_type:
            continue
    
        t = target_type.strip()
        t_lower = t.lower()
        base = t_lower.split('(')[0]
    
        if base in ['string','varchar','char']:
            continue
    
        if base == 'date':
            spark_exp = f"{col} IS NULL OR to_date({col}, 'yyyy-MM-dd') IS NOT NULL"
        else:
            
            spark_exp = f"{col} IS NULL OR CAST({col} AS {target_type}) IS NOT NULL"
    
        dtype_rules.append({
            "column": col,
            "rule_type": "dtype",
            "condition": target_type,
            "severity": "ERROR",
            "action": "FAIL_JOB",
            "description": f"value in {col} must be a valid {target_type}",
            "spark_exp": spark_exp
        })

            
        
        
    # load and build the rules
        
    s3_client = boto3.client('s3')
    contracts = s3_client.get_object(Bucket = bucket, Key = key)
    contracts = contracts['Body'].read().decode('utf-8')
    contracts = json.loads(contracts)
    
    all_rules = contracts.get('data_quality',{}).get('rules',[])
    # add the dtype issues to the llm rule 
    all_rules.extend(dtype_rules)
    
    final_rules = []
    
    for cur_rule in all_rules:
        cur_col = cur_rule.get('column','')
        cur_rtype = cur_rule.get('rule_type','')
        cur_spark_exp = cur_rule.get('spark_exp')
        if cur_spark_exp:
            if cur_col.upper() =='__TABLE__' or (cur_rtype in ('pk','fk')) or (cur_spark_exp.lower() == 'true'):
                continue 
            final_rules.append(cur_rule)
    
        
    errors = []
    sev_checks = []
    
    for rule in final_rules:
        sev = rule['severity']
        spark_exp = rule['spark_exp']
        error_msg = rule['description'] 
        
        error_cond = f.when(f.expr(f'NOT ({spark_exp})'), f.lit(error_msg)).otherwise(f.lit(None))
        sev_cond = f.when(f.expr(f'NOT ({spark_exp})'), f.lit(sev)).otherwise(f.lit(None))
        errors.append(error_cond)
        sev_checks.append(sev_cond)
        
    # apply the rules
    
    df = df.withColumn('all_errors', f.array(*(errors))).withColumn('all_sevchecks',f.array(*(sev_checks)))\
         .withColumn('Reason', f.expr("filter(all_errors, x -> x is not null)"))\
         .withColumn('DQ_severity', f.expr("filter(all_sevchecks, x -> x is not null)"))\
         .drop('all_errors', 'all_sevchecks')
         
    df_valid = df.filter(f.size('Reason')==0).drop('Reason','DQ_severity')
    df_invalid = df.filter(f.size('Reason')>0)
    
    df_invalid = df_invalid.withColumn('Reprocess_IND', f.when(f.array_contains(f.col('DQ_severity'), 'ERROR'), f.lit('N')).otherwise(f.lit('Y')))
    
    # date convertion
    
    for col,d_type in dtypes_check.items():
        if d_type.strip().lower() == 'date':
            df_valid = df_valid.withColumn(col, f.to_date(col,'yyyy-MM-dd'))
    
    # typecast to the orgininal table sttructure 
    
    for col_name, target_type in dtypes_check.items():
        if col_name not in df_valid.columns:
            continue
        if not target_type:
            continue
        t = target_type.strip()
        t_lower = t.lower()
        base = t_lower.split('(')[0]

        cast_type = t  

        if base in ['varchar','char']:
            cast_type = 'string'

        if cast_type.lower() != 'string':
            df_valid = df_valid.withColumn(col_name, f.col(col_name).cast(cast_type))
                
    df_valid = df_valid.select(list(dtypes_check.keys()))
    
    df_valid.write.format('parquet').option('path',valid_records_output).mode('overwrite').saveAsTable(f'{database}.{table}')
    df_invalid.write.format('parquet').option('path',invalid_records_output).mode('overwrite').saveAsTable(f'{database}.{table}_error')
        
    job.commit()
    
dq_rules(bucket,table,key)
        
    