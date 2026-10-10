from airflow.decorators import dag, task
from airflow.models import Variable
from datetime import datetime

BUCKET_NAME = "data"
DATASET_FILENAME = "Phishing_Email.csv"
KAGGLE_DATASET = "subhajournal/phishingemails"

@dag(
    dag_id="download_dataset",
    description="Descarga el dataset bajo demanda.",
    schedule=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["phishing_detection"]
)
def download_dataset():

    @task.virtualenv(
        task_id="dataset_download",
        requirements=[ "kagglehub==1.0.2" ],
        system_site_packages=True,
        env_vars={
            "KAGGLE_API_TOKEN": Variable.get("KAGGLE_API_TOKEN")
        }
    )
    def dataset_download(
        bucket_name: str,
        dataset_filename: str,
        kaggle_dataset: str,
    ) -> str:
        import boto3
        import kagglehub
        import uuid

        import os

        print(f"Descargando dataset '{kaggle_dataset}'.")
        local_path = kagglehub.dataset_download(
            handle=kaggle_dataset,
            path=dataset_filename,
        )
        key = f"datasets/raw/data_{uuid.uuid4().hex}.csv"
        s3_path = f"s3://{bucket_name}/{key}"
        print(f"Subiendo dataset a '{s3_path}'")
        with open(local_path, "rb") as f:
            boto3.client("s3").put_object(Bucket=bucket_name, Key=key, Body=f)
        os.remove(local_path)
        print(f"Dataset guardado en: {s3_path}")
        return s3_path

    _ = dataset_download(
        bucket_name=BUCKET_NAME,
        dataset_filename=DATASET_FILENAME,
        kaggle_dataset=KAGGLE_DATASET,
    )

dag = download_dataset()