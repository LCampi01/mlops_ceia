"""Reentrena el champion de MLflow, sea cual sea su algoritmo."""
from datetime import datetime, timedelta, timezone
from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
from train_pipeline import run_training_pipeline

default_args = {
    'owner': 'mlops_team',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 0,
}

with DAG(
    'phishing_champion_retrain',
    default_args=default_args,
    description='Reentrena el champion de phishing y registra una nueva versión challenger.',
    schedule='@monthly', # El día 1 de cada mes a las 00:00 UTC; también admite ejecución manual.
    start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
) as dag:

    task_train = PythonOperator(
        task_id='reentrenar_champion',
        python_callable=run_training_pipeline,
        execution_timeout=timedelta(minutes=30),
    )
