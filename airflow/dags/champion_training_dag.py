"""Reentrena el champion de MLflow incorporando feedback de producción."""
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

FEEDBACK_REQUIREMENTS = [
    "boto3~=1.34",
    "pandas>=2.2,<3",
    "sqlalchemy>=1.4,<3",
    "psycopg2-binary>=2.9",
]


@dag(
    dag_id="phishing_champion_retrain",
    description="Reentrena el champion de phishing incorporando feedback de producción.",
    schedule="@daily",  # Cada día a las 00:00 UTC; también admite ejecución manual.
    start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    default_args={"owner": "mlops_team", "retries": 0},
)
def phishing_champion_retrain():

    @task.virtualenv(
        task_id="recopilar_feedback",
        requirements=FEEDBACK_REQUIREMENTS,
        system_site_packages=True,
    )
    def recopilar_feedback(bucket: str, run_id: str) -> str:
        """Obtiene predicciones con feedback de las últimas 24 horas y las sube a S3.

        Lanza AirflowSkipException si no hay filas nuevas, propagando el skip
        a preparar_datos y reentrenar_champion sin registrar un error.
        Devuelve la clave S3 del CSV generado cuando sí hay filas nuevas.
        """
        import os
        import boto3
        import pandas as pd
        import sqlalchemy as sa
        from airflow.exceptions import AirflowSkipException

        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            raise ValueError("DATABASE_URL no está definida en el entorno de Airflow")

        engine = sa.create_engine(db_url, pool_pre_ping=True)
        query = sa.text(
            """
            SELECT email_text,
                   prediction_code,
                   feedback,
                   created_at
            FROM   predictions
            WHERE  feedback IS NOT NULL
            ORDER BY created_at DESC
            """
        )
        with engine.connect() as conn:
            rows = conn.execute(query).fetchall()
        engine.dispose()

        if not rows or not rows[-1]["created_at"] >= (pd.Timestamp.now() - pd.Timedelta(hours=24)):
            print("No hay feedback nuevo en las últimas 24 horas. Se omite el reentrenamiento.")
            raise AirflowSkipException("Sin feedback nuevo en las últimas 24 horas")

        df = pd.DataFrame(rows, columns=["email_text", "prediction_code", "feedback"])

        # Se invierte la etiqueta si el feedback es negativo.
        df["label"] = df.apply(
            lambda r: 1 - r["prediction_code"] if r["feedback"] == "NO" else r["prediction_code"],
            axis=1,
        ).astype(int)
        df = df[["email_text", "label"]].copy()

        print(f"Predicciones con feedback recuperadas: {len(df)}")
        print(df["label"].value_counts().to_dict())

        key = f"retrain/{run_id}/feedback.csv"
        s3 = boto3.client("s3")
        s3.put_object(Bucket=bucket, Key=key, Body=df.to_csv(index=False).encode())
        print(f"Feedback subido a s3://{bucket}/{key}")
        return key

    @task.virtualenv(
        task_id="preparar_datos",
        requirements=["boto3~=1.34", "pandas>=2.2,<3", "scikit-learn>=1.6,<1.7"],
        system_site_packages=True,
    )
    def preparar_datos(bucket: str, dataset_prefix: str, run_id: str, feedback_key: str) -> dict:
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
        df = df[["email_text", "label"]].copy()

        # --- Considera feedback productivo ----------------------------
        feedback_rows = 0
        df["_source"] = "base"
        if feedback_key:
            response = s3.get_object(Bucket=bucket, Key=feedback_key)
            try:
                df_feedback = pd.read_csv(response["Body"], keep_default_na=False)
            finally:
                response["Body"].close()
            if not {"email_text", "label"}.issubset(df_feedback.columns):
                raise ValueError("El CSV de feedback debe tener las columnas email_text y label")
            df_feedback["email_text"] = df_feedback["email_text"].str.strip()
            df_feedback["label"] = df_feedback["label"].astype(int)
            df["_source"] = "base"
            df_feedback["_source"] = "feedback"
            df = pd.concat([df, df_feedback], ignore_index=True)
            feedback_rows = len(df_feedback)
            print(f"Filas de feedback añadidas antes de limpiar: {feedback_rows}")
        # ----------------------------------------------------------------------

        normalized = df.email_text.str.lower().str.replace(r"<[^>]*>", " ", regex=True)
        df["normalized"] = normalized.str.replace(r"[^a-z]+", " ", regex=True).str.strip()
        df = df[~df.normalized.isin(["", "empty"])].copy()
        conflicts = df.groupby("normalized").label.transform("nunique") > 1

        df["_conflict"] = conflicts
        df = df[~(df["_conflict"] & (df["_source"] == "feedback"))].copy()

        remaining_conflicts = df.groupby("normalized").label.transform("nunique") > 1
        df = df[~remaining_conflicts].drop_duplicates("normalized")[["email_text", "label"]]
        if df.label.nunique() != 2 or df.label.value_counts().min() < 10:
            raise ValueError("Se necesitan al menos 10 correos diferentes por clase")

        train, rest = train_test_split(df, test_size=0.30, stratify=df.label, random_state=42)
        validation, test = train_test_split(rest, test_size=0.50, stratify=rest.label, random_state=42)

        keys = {}
        for name, partition in [("train", train), ("validation", validation), ("test", test)]:
            key = f"retrain/{run_id}/{name}.csv"
            s3.put_object(Bucket=bucket, Key=key, Body=partition.to_csv(index=False).encode())
            keys[name] = key
        print(f"Correos originales: {original_rows}; feedback: {feedback_rows}; limpios tras merge: {len(df)}")
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

    feedback_key = recopilar_feedback(
        bucket=BUCKET,
        run_id="{{ run_id }}",
    )
    keys = preparar_datos(
        bucket=BUCKET,
        dataset_prefix=DATASET_PREFIX,
        run_id="{{ run_id }}",
        feedback_key=feedback_key,
    )
    reentrenar_champion(
        keys=keys,
        bucket=BUCKET,
        model_name=MODEL_NAME,
        run_id="{{ run_id }}",
    )


dag = phishing_champion_retrain()
