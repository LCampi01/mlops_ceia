"""Pipeline del TP: preparar el CSV de Kaggle, comparar modelos y registrar el mejor."""
from datetime import datetime, timedelta, timezone
import os

from airflow import DAG
from airflow.models.param import Param
from airflow.providers.standard.operators.python import PythonOperator

BUCKET = "data"
DATASET_KEY = "datasets/Phishing_Email.csv"
EXPERIMENT_NAME = "phishing-comparison"
MODEL_NAME = "phishing_detector"


def preparar_datos(run_id):
    import boto3
    import pandas as pd
    from sklearn.model_selection import train_test_split

    # El DAG del compañero deja el CSV original en esta ubicación de RustFS.
    s3 = boto3.client("s3")
    response = s3.get_object(Bucket=BUCKET, Key=DATASET_KEY)
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

    # Detectar duplicados antes del split, conservando el texto original.
    normalized = df.email_text.str.lower().str.replace(r"<[^>]*>", " ", regex=True)
    df["normalized"] = normalized.str.replace(r"[^a-z]+", " ", regex=True).str.strip()
    df = df[~df.normalized.isin(["", "empty"])].copy()
    conflicts = df.groupby("normalized").label.transform("nunique") > 1
    df = df[~conflicts].drop_duplicates("normalized")[["email_text", "label"]]
    if df.label.nunique() != 2 or df.label.value_counts().min() < 10:
        raise ValueError("Se necesitan al menos 10 correos diferentes por clase")

    # Train aprende; validación elige el modelo; test se usa solo al final.
    train, rest = train_test_split(df, test_size=0.30, stratify=df.label, random_state=42)
    validation, test = train_test_split(rest, test_size=0.50, stratify=rest.label, random_state=42)

    # Las tareas comparten archivos por S3. XCom solo lleva sus nombres.
    keys = {}
    for name, partition in [("train", train), ("validation", validation), ("test", test)]:
        key = f"phishing/{run_id}/{name}.csv"
        s3.put_object(Bucket=BUCKET, Key=key, Body=partition.to_csv(index=False).encode())
        keys[name] = key
    print(f"Correos originales: {original_rows}; limpios: {len(df)}")
    print(f"Train: {len(train)}, validación: {len(validation)}, test: {len(test)}")
    return keys


def entrenar_modelos(ti, run_id, simular_comparacion=False):
    import random
    import boto3
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import mlflow
    import mlflow.sklearn
    import pandas as pd
    from sklearn.compose import ColumnTransformer
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import ConfusionMatrixDisplay, f1_score, precision_score, recall_score
    from sklearn.naive_bayes import MultinomialNB
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler
    from xgboost import XGBClassifier

    keys = ti.xcom_pull(task_ids="preparar_datos")
    s3 = boto3.client("s3")
    partitions = {}
    for name in ["train", "validation"]:
        response = s3.get_object(Bucket=BUCKET, Key=keys[name])
        try:
            partitions[name] = pd.read_csv(response["Body"], keep_default_na=False)
        finally:
            response["Body"].close()
    X_train = partitions["train"][["email_text"]]
    y_train = partitions["train"].label
    X_val = partitions["validation"][["email_text"]]
    y_val = partitions["validation"].label

    # Los límites de las categorías se calculan únicamente con entrenamiento.
    q1, q3 = X_train.email_text.str.split().str.len().quantile([0.25, 0.75])

    def extraer_atributos(X, q1, q3):
        # MLflow guarda esta función; los cuartiles son parámetros del transformador.
        import re
        import pandas as pd
        rows = []
        for text in X.email_text:
            text = text.lower()
            words = re.findall(r"[a-z]+", text)
            count = len(text.split())
            rows.append({
                "text": " ".join(re.findall(r"[a-z]+", re.sub(r"<[^>]*>", " ", text))),
                "has_link": int("http" in text),
                "domain_dot_high": int(any(url.count(".") > 3 for url in re.findall(r"https?://\S+", text))),
                "has_suspicious_tags": int("<script" in text or "<form" in text),
                "words_count_cat": "bajo" if count < q1 else "medio" if count < q3 else "largo",
                "imperative_verbs_count": sum(text.count(w) for w in ["click", "verify", "submit", "download", "update"]),
                "pronoun_density": sum(w in ["i", "you", "he", "she", "it", "we", "they"] for w in words) / max(len(words), 1),
                "urgency_markers_count": sum(text.count(w) for w in ["urgent", "asap", "immediately", "deadline"]),
            })
        return pd.DataFrame(rows, index=X.index)

    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    mlflow.set_experiment(EXPERIMENT_NAME)

    # Baseline del notebook: referencia para comparar con los modelos entrenados.
    features = extraer_atributos(X_val, q1, q3)
    score = (2 * (features.imperative_verbs_count > 0)
             + 2 * (features.pronoun_density > 0)
             + (features.urgency_markers_count > 0).astype(int)
             + 2 * features.domain_dot_high + 2 * features.has_suspicious_tags + features.has_link)
    with mlflow.start_run(run_name="baseline", tags={"airflow_run_id": run_id}):
        baseline_f1 = f1_score(y_val, score >= 3, zero_division=0)
        mlflow.log_metric("validation_f1", baseline_f1)
        print(f"Baseline: F1={baseline_f1:.4f}")

    models = {
        "naive_bayes": MultinomialNB(),
        "logistic_regression": LogisticRegression(max_iter=1000, solver="liblinear", random_state=42),
        "xgboost": XGBClassifier(
            n_estimators=200, max_depth=6, learning_rate=0.05, subsample=0.9,
            objective="binary:logistic", eval_metric="logloss", random_state=42, n_jobs=1,
        ),
    }
    results = []
    # Un bucle como en los notebooks: un entrenamiento y un run MLflow por modelo.
    for name, classifier in models.items():
        transformers = [("text", TfidfVectorizer(max_features=5000, stop_words="english"), "text")]
        if name != "naive_bayes":
            transformers.extend([
                ("binary", "passthrough", ["has_link", "domain_dot_high", "has_suspicious_tags"]),
                ("category", OneHotEncoder(handle_unknown="ignore"), ["words_count_cat"]),
                ("numeric", StandardScaler(with_mean=False), ["imperative_verbs_count", "pronoun_density", "urgency_markers_count"]),
            ])
        model = Pipeline([
            ("attributes", FunctionTransformer(extraer_atributos, kw_args={"q1": q1, "q3": q3})),
            ("features", ColumnTransformer(transformers, sparse_threshold=1.0)),
            ("classifier", classifier),
        ])
        with mlflow.start_run(run_name=name, tags={"airflow_run_id": run_id}) as run:
            mlflow.set_tag("selection_mode", "simulation" if simular_comparacion else "real")
            mlflow.log_params(classifier.get_params())
            mlflow.log_param("tfidf_max_features", 5000)
            mlflow.log_param("train_s3_key", keys["train"])
            model.fit(X_train, y_train)
            predictions = model.predict(X_val)
            f1 = f1_score(y_val, predictions, zero_division=0)
            # Solo para el TP: variar la selección sin modificar la métrica real.
            noise = random.uniform(-0.05, 0.05) if simular_comparacion else 0.0
            selection_f1 = max(0.0, min(1.0, float(f1) + noise))
            mlflow.log_metrics({
                "validation_f1": f1,
                "selection_f1": selection_f1,
                "selection_noise": noise,
                "validation_precision": precision_score(y_val, predictions, zero_division=0),
                "validation_recall": recall_score(y_val, predictions, zero_division=0),
            })
            plot = ConfusionMatrixDisplay.from_predictions(y_val, predictions)
            mlflow.log_figure(plot.figure_, "confusion_matrix.png")
            plt.close(plot.figure_)
            # Incluye preprocesamiento: permite predecir desde el texto original.
            mlflow.sklearn.log_model(model, "model", input_example=X_train.head(2))
            results.append({"name": name, "f1": float(f1), "selection_f1": selection_f1,
                            "simulated": simular_comparacion, "run_id": run.info.run_id})
            print(f"{name}: F1 real={f1:.4f}, F1 selección={selection_f1:.4f}, simulación={simular_comparacion}")
    return results


def registrar_mejor_modelo(ti):
    import boto3
    import mlflow
    import mlflow.sklearn
    import pandas as pd
    from sklearn.metrics import f1_score, precision_score, recall_score

    results = ti.xcom_pull(task_ids="entrenar_modelos")
    winner = max(results, key=lambda result: result["selection_f1"])
    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    model_uri = f"runs:/{winner['run_id']}/model"
    model = mlflow.sklearn.load_model(model_uri)

    # El test se mira recién después de elegir al ganador por validación.
    keys = ti.xcom_pull(task_ids="preparar_datos")
    response = boto3.client("s3").get_object(Bucket=BUCKET, Key=keys["test"])
    try:
        test = pd.read_csv(response["Body"], keep_default_na=False)
    finally:
        response["Body"].close()
    predictions = model.predict(test[["email_text"]])
    with mlflow.start_run(run_id=winner["run_id"]):
        mlflow.log_metrics({
            "test_f1": f1_score(test.label, predictions, zero_division=0),
            "test_precision": precision_score(test.label, predictions, zero_division=0),
            "test_recall": recall_score(test.label, predictions, zero_division=0),
        })
    version = mlflow.register_model(model_uri, MODEL_NAME)
    client = mlflow.MlflowClient()
    client.set_model_version_tag(MODEL_NAME, version.version, "selection_mode",
                                 "simulation" if winner["simulated"] else "real")
    client.set_registered_model_alias(MODEL_NAME, "challenger", version.version)
    # El primer ganador inicia el ciclo. Los siguientes se revisan antes de promoverlos.
    if "champion" not in client.get_registered_model(MODEL_NAME).aliases:
        client.set_registered_model_alias(MODEL_NAME, "champion", version.version)
    print(f"Ganador: {winner['name']}, F1 real: {winner['f1']:.4f}, "
          f"F1 selección: {winner['selection_f1']:.4f}, versión: {version.version}")
    return {**winner, "version": str(version.version)}


with DAG(
    "phishing_training", schedule="0 0 1 */3 *", catchup=False, max_active_runs=1,
    # Trimestres calendario: enero, abril, julio y octubre, a las 00:00 UTC.
    start_date=datetime(2026, 10, 1, tzinfo=timezone.utc),
    default_args={"owner": "mlops_team", "retries": 0},
    params={"simular_comparacion": Param(False, type="boolean",
            description="Demo del TP: sumar ruido al F1 de selección para probar distintos ganadores")},
    render_template_as_native_obj=True,
    description="Prepara correos, compara tres modelos y registra el mejor en MLflow.",
) as dag:
    prepare = PythonOperator(task_id="preparar_datos", python_callable=preparar_datos)
    train = PythonOperator(
        task_id="entrenar_modelos", python_callable=entrenar_modelos,
        op_kwargs={"simular_comparacion": "{{ params.simular_comparacion }}"},
        execution_timeout=timedelta(minutes=30),
    )
    register = PythonOperator(task_id="registrar_mejor_modelo", python_callable=registrar_mejor_modelo)
    prepare >> train >> register
