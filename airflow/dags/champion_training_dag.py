"""Reentrena el champion de MLflow, sea cual sea su algoritmo."""
from datetime import datetime, timedelta, timezone

from airflow.decorators import dag, task

BUCKET = "data"
MODEL_NAME = "phishing_detector"
DATASET_PREFIX = "datasets/raw/data_"

ML_REQUIREMENTS = [
    "boto3~=1.34",
    "mlflow[extras]==2.22.5",
    "scikit-learn>=1.6,<1.7",
    "pandas>=2.2,<3",
]


@dag(
    dag_id="phishing_champion_retrain",
    description="Reentrena el champion de phishing y registra una nueva versión challenger.",
    schedule="@monthly",  # El día 1 de cada mes a las 00:00 UTC; también admite ejecución manual.
    start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    default_args={"owner": "mlops_team", "retries": 0},
)
def phishing_champion_retrain():

    @task.virtualenv(
        task_id="preparar_datos",
        requirements=["boto3~=1.34", "pandas>=2.2,<3", "scikit-learn>=1.6,<1.7"],
        system_site_packages=True,
    )
    def preparar_datos(bucket: str, dataset_prefix: str, run_id: str) -> dict:
        import boto3
        import pandas as pd
        from sklearn.model_selection import train_test_split

        def obtener_ultimo_dataset(s3):
            pages = s3.get_paginator("list_objects_v2").paginate(
                Bucket=bucket, Prefix=dataset_prefix,
            )
            datasets = (
                obj
                for page in pages
                for obj in page.get("Contents", [])
                if obj["Key"].endswith(".csv")
            )
            latest = max(datasets, key=lambda obj: (obj["LastModified"], obj["Key"]), default=None)
            if latest is None:
                raise ValueError(f"No hay datasets en s3://{bucket}/{dataset_prefix}*.csv.")
            return latest["Key"]

        s3 = boto3.client("s3")
        dataset_key = obtener_ultimo_dataset(s3)
        print(f"Dataset seleccionado: s3://{bucket}/{dataset_key}")
        response = s3.get_object(Bucket=bucket, Key=dataset_key)
        try:
            df = pd.read_csv(response["Body"])
        finally:
            response["Body"].close()

        if not {"Email Text", "Email Type"}.issubset(df.columns):
            raise ValueError("El CSV debe tener las columnas Email Text y Email Type")
        original_rows = len(df)
        df = df.dropna(subset=["Email Text", "Email Type"]).copy()
        labels = {"Safe Email": 0, "Phishing Email": 1}
        if not df["Email Type"].isin(labels).all():
            raise ValueError("Hay etiquetas distintas de Safe Email y Phishing Email")
        df["label"] = df["Email Type"].map(labels)
        df["email_text"] = df["Email Text"].str.strip()

        normalized = df.email_text.str.lower().str.replace(r"<[^>]*>", " ", regex=True)
        df["normalized"] = normalized.str.replace(r"[^a-z]+", " ", regex=True).str.strip()
        df = df[~df.normalized.isin(["", "empty"])].copy()
        conflicts = df.groupby("normalized").label.transform("nunique") > 1
        df = df[~conflicts].drop_duplicates("normalized")[["email_text", "label"]]
        if df.label.nunique() != 2 or df.label.value_counts().min() < 10:
            raise ValueError("Se necesitan al menos 10 correos diferentes por clase")

        train, rest = train_test_split(df, test_size=0.30, stratify=df.label, random_state=42)
        validation, test = train_test_split(rest, test_size=0.50, stratify=rest.label, random_state=42)

        keys = {}
        for name, partition in [("train", train), ("validation", validation), ("test", test)]:
            key = f"retrain/{run_id}/{name}.csv"
            s3.put_object(Bucket=bucket, Key=key, Body=partition.to_csv(index=False).encode())
            keys[name] = key
        print(f"Correos originales: {original_rows}; limpios: {len(df)}")
        print(f"Train: {len(train)}, validación: {len(validation)}, test: {len(test)}")
        return keys

    @task.virtualenv(
        task_id="reentrenar_champion",
        requirements=ML_REQUIREMENTS,
        system_site_packages=True,
        execution_timeout=timedelta(minutes=30),
    )
    def reentrenar_champion(
        keys: dict,
        bucket: str,
        model_name: str,
        run_id: str,
    ) -> dict:
        import os
        import boto3
        import mlflow
        import mlflow.sklearn
        import pandas as pd
        from mlflow.exceptions import MlflowException
        from sklearn.base import clone
        from sklearn.metrics import f1_score, precision_score, recall_score

        mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
        client = mlflow.MlflowClient()

        try:
            registered = client.get_registered_model(model_name)
        except MlflowException as error:
            if error.error_code != "RESOURCE_DOES_NOT_EXIST":
                raise
            raise ValueError(
                "Primero ejecutá phishing_training para crear el champion"
            ) from error
        if "champion" not in registered.aliases:
            raise ValueError(
                "Asigná el alias champion a una versión de phishing_detector en MLflow"
            )

        champion_version = registered.aliases["champion"]
        champion = mlflow.sklearn.load_model(f"models:/{model_name}/{champion_version}")

        # clone conserva el algoritmo e hiperparámetros, pero borra el aprendizaje previo.
        model = clone(champion)
        classifier = model.named_steps["classifier"]
        model_class_name = type(classifier).__name__
        print(f"Reentrenando {model_class_name}, champion versión {champion_version}")

        s3 = boto3.client("s3")
        partitions = {}
        for name in ["train", "validation", "test"]:
            response = s3.get_object(Bucket=bucket, Key=keys[name])
            try:
                partitions[name] = pd.read_csv(response["Body"], keep_default_na=False)
            finally:
                response["Body"].close()

        train = partitions["train"]
        q1, q3 = train.email_text.str.split().str.len().quantile([0.25, 0.75])
        model.set_params(attributes__kw_args={"q1": q1, "q3": q3})

        mlflow.set_experiment("phishing-retraining")
        with mlflow.start_run(
            run_name=model_class_name,
            tags={"airflow_run_id": run_id, "champion_version": str(champion_version)},
        ) as run:
            mlflow.log_params(classifier.get_params())
            mlflow.log_param("train_s3_key", keys["train"])

            # Se vuelven a ajustar TF-IDF, encoders, escaladores y clasificador.
            model.fit(train[["email_text"]], train.label)

            for name in ["validation", "test"]:
                partition = partitions[name]
                predictions = model.predict(partition[["email_text"]])
                metrics = {
                    f"{name}_f1": f1_score(partition.label, predictions, zero_division=0),
                    f"{name}_precision": precision_score(partition.label, predictions, zero_division=0),
                    f"{name}_recall": recall_score(partition.label, predictions, zero_division=0),
                }
                mlflow.log_metrics(metrics)
                print(metrics)

            mlflow.sklearn.log_model(model, "model", input_example=train[["email_text"]].head(2))
            model_uri = f"runs:/{run.info.run_id}/model"

        version = mlflow.register_model(model_uri, model_name)
        client.set_registered_model_alias(model_name, "challenger", version.version)
        print(f"Nueva versión {version.version}. El champion sigue siendo {champion_version}.")
        return {
            "name": model_class_name,
            "version": str(version.version),
            "model_uri": model_uri,
        }

    keys = preparar_datos(
        bucket=BUCKET,
        dataset_prefix=DATASET_PREFIX,
        run_id="{{ run_id }}",
    )
    reentrenar_champion(
        keys=keys,
        bucket=BUCKET,
        model_name=MODEL_NAME,
        run_id="{{ run_id }}",
    )


dag = phishing_champion_retrain()
