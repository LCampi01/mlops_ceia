from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta

import sys
sys.path.append("/opt/airflow/dags")

from kaggle_pipeline import download_dataset

with DAG(
    "download_dataset",
    default_args={
        "owner": "mlops_team",
        "depends_on_past": False,
        "email_on_failure": False,
        "email_on_retry": False,
        "retries": 2,
        "retry_delay": timedelta(minutes=3),
    },
    description=("Descarga dataset y lo almacena en directorio local."),
    schedule=None,
    start_date=datetime(2026, 10, 6),
    catchup=False,
) as dag:

    task_download = PythonOperator(
        task_id="download_kaggle_dataset",
        python_callable=download_dataset,
    )

    task_download
