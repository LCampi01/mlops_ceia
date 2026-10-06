# MLOps CEIA

## Integrantes
* Tomás Abraham (a2602)
* Carlos Agustín Berdaguer (a2605)
* Lucas Ezequiel Campi (a2609)
* José Miguel Silva Pavón (a2415)

## Objetivo
Servir un modelo de detección de _spam_ en un stack de MLFlow / Airflow / FastAPI.

## Arqitectura

### DAG Airflow
1. Se descarga el dataset desde Kaggle.
    - El dataset es: https://www.kaggle.com/datasets/subhajournal/phishingemails
    - Se usan credenciales configuradas para acceder a la API de Kaggle.
2. Se valida el dataset descargado sin modificar.
    - Se valida la integridad del archivo descargado.
    - Se valida la estructura.
    - El dataset se almacena de forma local.
3. Se realizan las transformaciones necesarias al dataset.
    - Se aplican las transformaciones originales realizadas en `notebooks/eda.ipynb`.
    - Se guardan los datos transformados para el entrenamiento.
4. Se entrena el modelo y se registran métricas y parámetros en MLFlow.
    - Se carga le dataset transformado para entrenamiento y validación.
    - Se buscan parámetros óptimos con búsqueda de hiperparámetros.
    - Se entrena el modelo.
    - Se evalúan métricas.
    - Se registran en Mlflow.
    - Se registra el modelo en Mlflow.

### Mlflow
Se registran los experimentos, parámetros y métricas, modelos como artefactos y se dejan disponibles en el model registry.

### FastAPI
Se sirve una API REST para acceder a las predicciones del modelo.

## Ejecución local

### Precondiciones
Copiar el archivo `.env.example` a `.env` y poner valores serios.

### Comandos
* Para prenderlo:
```console
$ ./setup.sh
```
* Para pararlo:
```console
./setup.sh --stop
```
* Para destruir todo:
```console
./setup.sh --destroy
```

## Credenciales del stack

### ~~Minio~~ RustFS
* user: `secret-user`
* pass: `RUSTFS_SECRET_KEY` de `.env`

### Airflow
* user: `secret-user`
* pass: `_AIRFLOW_WWW_USER_PASSWORD` de `.env`

### MLflow
* user: `secret-user`
* pass: `MLFLOW_AUTH_ADMIN_PASSWORD` de `.env`
