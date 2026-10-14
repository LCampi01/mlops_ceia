# 14/10/2026
- Las bases `mlflow_db` y `fastapi` se crean en cada arranque si faltan, también con un volumen de Postgres existente.
- Endpoint `GET /predictions/{prediction_id}` y header `Location` corregido para apuntar a él.

# 12/10/2026
- Búsqueda de hiperparámetros con Optuna (TPE, 3-fold CV sobre train) por modelo, con early stopping configurable por `patience` y `min_trials`. Se registran `best_cv_f1` y `optuna_trials_run` en MLflow.
- Endpoint `POST /predictions/{prediction_id}/feedback` para registrar si la predicción fue correcta (`OK`) o incorrecta (`NO`).

# 08/10/2026
- Modo de simulación opcional para variar aleatoriamente el F1 de selección y probar distintos ganadores, conservando las métricas reales en MLflow.
- DAG trimestral para preparar datos, comparar modelos y registrar el mejor en MLflow. Los tres modelos (Naive Bayes, regresión logística, XGBoost) se entrenan en paralelo; el baseline heurístico corre en paralelo también.
- Reentrenamiento mensual del `champion`, conservando su algoritmo e hiperparámetros y registrando un nuevo `challenger`.
- API de predicción desde texto usando el `champion`, con actualización al cambiar su versión en MLflow. Las predicciones se persisten en PostgreSQL con su texto, resultado y versión del modelo.
- Ajustes de credenciales, buckets y dependencias en Docker Compose e imágenes de Airflow y FastAPI.
- Explicación de los DAGs, sus frecuencias y el flujo de modelos integrada en el README.

# 01/10/2026
- Fix de contraseña por defecto de Mlflow.
- Fix de valor por defecto para `MLFLOW_ALLOWED_HOSTS`.
- Fix de instalación de `psycopg[binary]` en imagen de Mlflow para soportar `auth`.
- CI para cambios de dependencias en Airflow.
