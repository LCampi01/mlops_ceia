import os

BUCKET_NAME = "data"
DATASET_FILENAME = "Phishing_Email.csv"
KAGGLE_DATASET = "subhajournal/phishingemails"

def download_dataset() -> str:
    import boto3
    import kaggle
    if not os.environ.get("KAGGLE_API_TOKEN"):
        raise EnvironmentError(
            "No se encontraron las credenciales de Kaggle. "
            "Configurar variable de entorno KAGGLE_API_TOKEN."
        )
    kaggle.api.authenticate()
    print(f"Descargando dataset '{KAGGLE_DATASET}'.")
    response = kaggle.api.kaggle_api_extended.datasets_download_file_with_http_info(
        dataset=KAGGLE_DATASET,
        file_name=DATASET_FILENAME,
        _preload_content=False
    )
    s3_client = boto3.client("s3")
    s3_key = f"datasets/{DATASET_FILENAME}"
    s3_path = f"s3://{BUCKET_NAME}/{s3_key}"
    print(f"Subiendo dataset a '{s3_path}'")
    print(s3_client.upload_fileobj(
        Fileobj=response[0],
        Bucket=BUCKET_NAME,
        Key=s3_key
    )
    print(f"Dataset guardado en: {s3_path}")
    return s3_path
