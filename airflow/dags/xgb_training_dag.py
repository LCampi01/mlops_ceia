# dags/xgb_training_dag.py
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
import sys

# Asegúrate de que el path a tus módulos esté disponible
sys.path.append('/opt/airflow/dags') 
from train_pipeline import run_training_pipeline

default_args = {
    'owner': 'mlops_team',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

with DAG(
    'xgb_phishing_retrain_pipeline',
    default_args=default_args,
    description='Pipeline de re-entrenamiento de modelo XGBoost para detección de phishing',
    schedule='@monthly', # Se ejecuta mensualmente o manualmente
    start_date=datetime(2026, 1, 1),
    catchup=False,
) as dag:

    task_train = PythonOperator(
        task_id='run_xgboost_training',
        python_callable=run_training_pipeline
    )

    task_train