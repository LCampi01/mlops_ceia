# MLOps CEIA

## Integrantes
* Tomás Abraham (a2602)
* Carlos Agustín Berdaguer (a2605)
* Lucas Ezequiel Campi (a2609)
* José Miguel Silva Pavón (a2415)

## Objetivo
Servir un modelo de detección de _phishing_ en un stack de MLFlow / Airflow / FastAPI.

## Arquitectura

### DAGs de Airflow

| DAG | Qué hace | Frecuencia |
| --- | --- | --- |
| [`download_dataset`](airflow/dags/download_dataset_dag.py) | Descarga el dataset de Kaggle y lo sube a RustFS. | Manual |
| [`phishing_training`](airflow/dags/phishing_training_dag.py) | Compara Naive Bayes, regresión logística y XGBoost (Optuna) y registra el mejor en MLflow. | Trimestral |
| [`phishing_champion_retrain`](airflow/dags/champion_training_dag.py) | Reentrena el `champion` incorporando feedback de producción y lo registra como `challenger`. | Diario |

`phishing_training` lee el CSV más reciente de RustFS, separa 70/15/15
(train/validación/test), busca hiperparámetros con Optuna y elige el modelo con
mayor F1 de validación. Acepta el parámetro `simular_comparacion` para sumar
ruido al F1 de selección y probar distintos ganadores.

`phishing_champion_retrain` recopila las predicciones con feedback de las
últimas 24 h desde PostgreSQL, las combina con el dataset base (en caso de
conflicto el dataset base tiene prioridad) y reajusta el pipeline del
`champion`. Si no hay feedback nuevo, se omite automáticamente.

Ambos DAGs admiten ejecución manual y no se disparan entre sí.

### MLflow

Registra parámetros, métricas y modelos (pipeline completo con preprocesamiento).
Experimentos: `phishing-comparison` (comparaciones) y `phishing-retraining`
(reentrenamientos). El modelo registrado se llama `phishing_detector` con dos aliases:

- `champion`: versión que usa la API para predecir.
- `challenger`: nuevo candidato pendiente de revisión.

El primer ganador recibe ambos aliases. Los siguientes se registran solo como
`challenger`; promover a `champion` se hace manualmente desde MLflow.

### FastAPI

Todos los endpoints (salvo `GET /`) requieren la cabecera `X-API-Key` con el
valor de `API_KEY` de `.env`. Usa el `champion` de MLflow y recarga
automáticamente cuando cambia el alias.

| Método | Ruta | Descripción |
| --- | --- | --- |
| `POST` | `/predictions` | Clasifica un correo. Devuelve 201 con la predicción y la persiste en PostgreSQL. |
| `GET` | `/predictions/{id}` | Consulta una predicción guardada (sin el texto del correo). |
| `POST` | `/predictions/{id}/feedback` | Registra feedback (`OK` o `NO`) sobre una predicción. Devuelve 204. |

Documentación interactiva en `http://localhost:8800/docs`.

## Ejecución local

### Comandos
* Para prenderlo:
```console
$ ./setup.sh
```
* Para pararlo:
```console
./setup.sh --stop
```
* Para destruir todo (borra también los volúmenes con datasets y modelos):
```console
./setup.sh --destroy
```

### Uso
Con el stack levantado, primero descargar el CSV a RustFS ejecutando el DAG de descarga de dataset; luego ejecutar
`phishing_training` desde `http://localhost:8080` para crear el primer champion.
Luego se puede ejecutar `phishing_champion_retrain`. Para usar datos nuevos,
hay que actualizar antes el CSV mediante la descarga.
Los resultados se consultan en `http://localhost:5000`.

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

### FastAPI
* cabecera `X-API-Key`: `API_KEY` de `.env`
