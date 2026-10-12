"""Reentrenamiento del modelo elegido en MLflow, sin fijar un clasificador."""


def run_training_pipeline(run_id):
    import os
    import boto3
    import mlflow
    import mlflow.sklearn
    import pandas as pd
    from mlflow.exceptions import MlflowException
    from sklearn.base import clone
    from sklearn.metrics import f1_score, precision_score, recall_score
    from phishing_training_dag import BUCKET, MODEL_NAME, preparar_datos

    # Resolver el alias una vez y trabajar con esa versión durante toda la ejecución.
    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    client = mlflow.MlflowClient()
    try:
        registered = client.get_registered_model(MODEL_NAME)
    except MlflowException as error:
        if error.error_code != "RESOURCE_DOES_NOT_EXIST":
            raise
        raise ValueError("Primero ejecutá phishing_training para crear el champion") from error
    if "champion" not in registered.aliases:
        raise ValueError("Asigná el alias champion a una versión de phishing_detector en MLflow")
    champion_version = registered.aliases["champion"]
    champion = mlflow.sklearn.load_model(f"models:/{MODEL_NAME}/{champion_version}")

    # clone conserva el algoritmo e hiperparámetros, pero borra el aprendizaje previo.
    model = clone(champion)
    classifier = model.named_steps["classifier"]
    model_name = type(classifier).__name__
    print(f"Reentrenando {model_name}, champion versión {champion_version}")

    # Reutilizar la preparación del otro DAG sobre el CSV actual de RustFS.
    keys = preparar_datos(f"retrain/{run_id}")
    s3 = boto3.client("s3")
    partitions = {}
    for name in ["train", "validation", "test"]:
        response = s3.get_object(Bucket=BUCKET, Key=keys[name])
        try:
            partitions[name] = pd.read_csv(response["Body"], keep_default_na=False)
        finally:
            response["Body"].close()
    train = partitions["train"]
    q1, q3 = train.email_text.str.split().str.len().quantile([0.25, 0.75])
    model.set_params(attributes__kw_args={"q1": q1, "q3": q3})

    mlflow.set_experiment("phishing-retraining")
    with mlflow.start_run(run_name=model_name, tags={
        "airflow_run_id": run_id, "champion_version": str(champion_version),
    }) as run:
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

    version = mlflow.register_model(model_uri, MODEL_NAME)
    client.set_registered_model_alias(MODEL_NAME, "challenger", version.version)
    print(f"Nueva versión {version.version}. El champion sigue siendo {champion_version}.")
    return {"name": model_name, "version": str(version.version), "model_uri": model_uri}
