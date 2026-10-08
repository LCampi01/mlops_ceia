# 08/10/2026

- Modo de simulación opcional para variar aleatoriamente el F1 de selección y probar distintos ganadores, conservando las métricas reales en MLflow.
- DAG trimestral para preparar datos, comparar modelos y registrar el mejor en MLflow.
- Reentrenamiento mensual del `champion`, conservando su algoritmo e hiperparámetros y registrando un nuevo `challenger`.
- API de predicción desde texto usando el `champion`, con actualización al cambiar su versión en MLflow.
- Ajustes de credenciales, buckets y dependencias en Docker Compose e imágenes de Airflow y FastAPI.
- Explicación de los DAGs, sus frecuencias y el flujo de modelos integrada en el README.

# 01/10/2026
- Fix de contraseña por defecto de Mlflow.
- Fix de valor por defecto para `MLFLOW_ALLOWED_HOSTS`.
- Fix de instalación de `psycopg[binary]` en imagen de Mlflow para soportar `auth`.
- CI para cambios de dependencias en Airflow.
