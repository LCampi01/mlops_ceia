"""Pipeline del TP: preparar el CSV de Kaggle, comparar modelos y registrar el mejor."""
from datetime import datetime, timedelta, timezone

from airflow.decorators import dag, task
from airflow.models import Variable
from airflow.models.param import Param

BUCKET = "data"
DATASET_PREFIX = "datasets/raw/data_"
EXPERIMENT_NAME = "phishing-comparison"
MODEL_NAME = "phishing_detector"

ML_REQUIREMENTS = [
    "boto3~=1.34",
    "mlflow[extras]==2.22.5",
    "optuna==4.3.0",
    "scipy>=1.18.0",
    "xgboost>=3.3.0",
    "scikit-learn>=1.6,<1.7",
    "pandas>=2.2,<3",
    "matplotlib>=3.9,<4",
]


@dag(
    dag_id="phishing_training",
    schedule="0 0 1 */3 *",
    catchup=False,
    max_active_runs=1,
    # Trimestres calendario: enero, abril, julio y octubre, a las 00:00 UTC.
    start_date=datetime(2026, 10, 1, tzinfo=timezone.utc),
    default_args={"owner": "mlops_team", "retries": 0},
    params={
        "simular_comparacion": Param(False, type="boolean",
            description="Demo del TP: sumar ruido al F1 de selección para probar distintos ganadores"),
        "n_trials": Param(30, type="integer", minimum=1,
            description="Número de trials de Optuna por modelo"),
        "patience": Param(10, type="integer", minimum=1,
            description="Trials consecutivos sin mejora antes de detener la búsqueda"),
        "min_trials": Param(10, type="integer", minimum=1,
            description="Mínimo de trials antes de que el early stopping pueda activarse"),
    },
    render_template_as_native_obj=True,
    description="Prepara correos, compara tres modelos y registra el mejor en MLflow.",
)
def phishing_training():

    @task.virtualenv(
        task_id="preparar_datos",
        requirements=["boto3~=1.34", "pandas>=2.2,<3", "scikit-learn>=1.6,<1.7"],
        system_site_packages=True,
    )
    def preparar_datos(bucket: str, dataset_prefix: str, run_id: str) -> dict:
        import boto3
        import pandas as pd
        from sklearn.model_selection import train_test_split

        # obtener_ultimo_dataset se define aquí porque el cuerpo de @task.virtualenv
        # se serializa y ejecuta en un subproceso aislado; las funciones del módulo
        # principal no están disponibles en ese contexto.
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
                raise ValueError(
                    f"No hay datasets en s3://{bucket}/{dataset_prefix}*.csv."
                )
            return latest["Key"]

        # Cada descarga genera un nombre nuevo; usar la más reciente por fecha de subida.
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
            s3.put_object(Bucket=bucket, Key=key, Body=partition.to_csv(index=False).encode())
            keys[name] = key
        print(f"Correos originales: {original_rows}; limpios: {len(df)}")
        print(f"Train: {len(train)}, validación: {len(validation)}, test: {len(test)}")
        return keys

    @task.virtualenv(
        task_id="calcular_baseline",
        requirements=ML_REQUIREMENTS,
        system_site_packages=True,
    )
    def calcular_baseline(
        keys: dict,
        bucket: str,
        experiment_name: str,
        run_id: str,
    ) -> None:
        import os
        import boto3
        import pandas as pd
        import mlflow
        from sklearn.metrics import f1_score

        s3 = boto3.client("s3")
        partitions = {}
        for name in ["train", "validation"]:
            response = s3.get_object(Bucket=bucket, Key=keys[name])
            try:
                partitions[name] = pd.read_csv(response["Body"], keep_default_na=False)
            finally:
                response["Body"].close()
        X_train = partitions["train"][["email_text"]]
        X_val = partitions["validation"][["email_text"]]
        y_val = partitions["validation"].label

        q1, q3 = X_train.email_text.str.split().str.len().quantile([0.25, 0.75])

        def extraer_atributos(X, q1, q3):
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
        mlflow.set_experiment(experiment_name)

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

    @task.virtualenv(
        requirements=ML_REQUIREMENTS,
        system_site_packages=True,
        execution_timeout=timedelta(minutes=90),
    )
    def entrenar_modelo(
        model_name: str,
        keys: dict,
        bucket: str,
        experiment_name: str,
        simular_comparacion: bool,
        n_trials: int,
        patience: int,
        min_trials: int,
        run_id: str,
    ) -> dict:
        import os
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
        from sklearn.naive_bayes import MultinomialNB
        from sklearn.metrics import ConfusionMatrixDisplay, f1_score, precision_score, recall_score
        from sklearn.model_selection import cross_val_score, StratifiedKFold
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler
        from xgboost import XGBClassifier
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        s3 = boto3.client("s3")
        partitions = {}
        for name in ["train", "validation"]:
            response = s3.get_object(Bucket=bucket, Key=keys[name])
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

        def construir_pipeline(trial):
            tfidf_max_features = trial.suggest_int("tfidf_max_features", 1000, 10000, step=1000)
            tfidf = TfidfVectorizer(max_features=tfidf_max_features, stop_words="english")
            if model_name == "naive_bayes":
                alpha = trial.suggest_float("alpha", 1e-3, 10.0, log=True)
                classifier = MultinomialNB(alpha=alpha)
                transformers = [("text", tfidf, "text")]
            elif model_name == "logistic_regression":
                C = trial.suggest_float("C", 1e-3, 100.0, log=True)
                classifier = LogisticRegression(C=C, max_iter=1000, solver="liblinear", random_state=42)
                transformers = [
                    ("text", tfidf, "text"),
                    ("binary", "passthrough", ["has_link", "domain_dot_high", "has_suspicious_tags"]),
                    ("category", OneHotEncoder(handle_unknown="ignore"), ["words_count_cat"]),
                    ("numeric", StandardScaler(with_mean=False), ["imperative_verbs_count", "pronoun_density", "urgency_markers_count"]),
                ]
            else:
                classifier = XGBClassifier(
                    n_estimators=trial.suggest_int("n_estimators", 50, 400),
                    max_depth=trial.suggest_int("max_depth", 3, 10),
                    learning_rate=trial.suggest_float("learning_rate", 1e-3, 0.3, log=True),
                    subsample=trial.suggest_float("subsample", 0.5, 1.0),
                    colsample_bytree=trial.suggest_float("colsample_bytree", 0.5, 1.0),
                    objective="binary:logistic", eval_metric="logloss", random_state=42, n_jobs=1,
                )
                transformers = [
                    ("text", tfidf, "text"),
                    ("binary", "passthrough", ["has_link", "domain_dot_high", "has_suspicious_tags"]),
                    ("category", OneHotEncoder(handle_unknown="ignore"), ["words_count_cat"]),
                    ("numeric", StandardScaler(with_mean=False), ["imperative_verbs_count", "pronoun_density", "urgency_markers_count"]),
                ]
            return Pipeline([
                ("attributes", FunctionTransformer(extraer_atributos, kw_args={"q1": q1, "q3": q3})),
                ("features", ColumnTransformer(transformers, sparse_threshold=1.0)),
                ("classifier", classifier),
            ])

        mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
        mlflow.set_experiment(experiment_name)

        with mlflow.start_run(run_name=model_name, tags={"airflow_run_id": run_id}) as run:
            mlflow.set_tag("selection_mode", "simulation" if simular_comparacion else "real")

            def objective(trial):
                pipeline = construir_pipeline(trial)
                # La búsqueda se hace con CV sobre train; validación queda intacta.
                scores = cross_val_score(
                    pipeline, X_train, y_train,
                    cv=StratifiedKFold(n_splits=3, shuffle=True, random_state=42),
                    scoring="f1", n_jobs=1,
                )
                cv_f1 = float(scores.mean())
                print(f"Ejecutando {trial.number} para el modelo {model_name} con params={trial.params}")
                with mlflow.start_run(run_name=f"{model_name}_trial_{trial.number}",
                                      nested=True, tags={"airflow_run_id": run_id}):
                    mlflow.log_params(trial.params)
                    mlflow.log_metric("cv_f1", cv_f1)
                return cv_f1

            def early_stopping_callback(study, trial):
                if len(study.trials) < min_trials:
                    return
                best = study.best_value
                recent = [t.value for t in study.trials[-patience:] if t.value is not None]
                if recent and max(recent) < best:
                    raise optuna.exceptions.StopStudyError

            study = optuna.create_study(direction="maximize")
            study.optimize(
                objective,
                n_trials=n_trials,
                callbacks=[early_stopping_callback],
                show_progress_bar=False,
            )
            trials_run = len(study.trials)
            print(f"{model_name}: trials ejecutados={trials_run}/{n_trials}, "
                  f"mejor trial={study.best_trial.number}, CV F1={study.best_value:.4f}, "
                  f"params={study.best_params}")
            mlflow.log_metric("optuna_trials_run", trials_run)

            # Reentrenar con los mejores hiperparámetros sobre todo el conjunto train.
            best_pipeline = construir_pipeline(study.best_trial)
            mlflow.log_params(study.best_params)
            mlflow.log_metric("best_cv_f1", study.best_value)
            best_pipeline.fit(X_train, y_train)
            predictions = best_pipeline.predict(X_val)
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
            mlflow.sklearn.log_model(best_pipeline, "model", input_example=X_train.head(2))
            print(f"{model_name}: F1 real={f1:.4f}, F1 selección={selection_f1:.4f}, simulación={simular_comparacion}")
            return {"name": model_name, "f1": float(f1), "selection_f1": selection_f1,
                    "simulated": simular_comparacion, "run_id": run.info.run_id}

    @task.virtualenv(
        task_id="registrar_mejor_modelo",
        requirements=ML_REQUIREMENTS,
        system_site_packages=True,
    )
    def registrar_mejor_modelo(
        results: list,
        keys: dict,
        bucket: str,
        model_name: str,
    ) -> dict:
        import os
        import boto3
        import mlflow
        import mlflow.sklearn
        import pandas as pd
        from sklearn.metrics import f1_score, precision_score, recall_score

        winner = max(results, key=lambda result: result["selection_f1"])
        mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
        model_uri = f"runs:/{winner['run_id']}/model"
        model = mlflow.sklearn.load_model(model_uri)

        # El test se mira recién después de elegir al ganador por validación.
        response = boto3.client("s3").get_object(Bucket=bucket, Key=keys["test"])
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
        version = mlflow.register_model(model_uri, model_name)
        client = mlflow.MlflowClient()
        client.set_model_version_tag(model_name, version.version, "selection_mode",
                                     "simulation" if winner["simulated"] else "real")
        client.set_registered_model_alias(model_name, "challenger", version.version)
        # El primer ganador inicia el ciclo. Los siguientes se revisan antes de promoverlos.
        if "champion" not in client.get_registered_model(model_name).aliases:
            client.set_registered_model_alias(model_name, "champion", version.version)
        print(f"Ganador: {winner['name']}, F1 real: {winner['f1']:.4f}, "
              f"F1 selección: {winner['selection_f1']:.4f}, versión: {version.version}")
        return {**winner, "version": str(version.version)}

    keys = preparar_datos(
        bucket=BUCKET,
        dataset_prefix=DATASET_PREFIX,
        run_id="{{ run_id }}",
    )
    TRAINING_KWARGS = dict(
        keys=keys,
        bucket=BUCKET,
        experiment_name=EXPERIMENT_NAME,
        simular_comparacion="{{ params.simular_comparacion }}",
        n_trials="{{ params.n_trials }}",
        patience="{{ params.patience }}",
        min_trials="{{ params.min_trials }}",
        run_id="{{ run_id }}",
    )
    calcular_baseline(
        keys=keys,
        bucket=BUCKET,
        experiment_name=EXPERIMENT_NAME,
        run_id="{{ run_id }}",
    )
    nb_result = entrenar_modelo.override(task_id="entrenar_naive_bayes")(
        model_name="naive_bayes", **TRAINING_KWARGS
    )
    lr_result = entrenar_modelo.override(task_id="entrenar_logistic_regression")(
        model_name="logistic_regression", **TRAINING_KWARGS
    )
    xgb_result = entrenar_modelo.override(task_id="entrenar_xgboost")(
        model_name="xgboost", **TRAINING_KWARGS
    )
    registrar_mejor_modelo(
        results=[nb_result, lr_result, xgb_result],
        keys=keys,
        bucket=BUCKET,
        model_name=MODEL_NAME,
    )


dag = phishing_training()
