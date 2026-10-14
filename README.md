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
| `download_dataset` | Descarga el dataset de phishing desde Kaggle y lo guarda en RustFS como `datasets/raw/data_<uuid>.csv`. | Manual |
| [`phishing_training`](airflow/dags/phishing_training_dag.py) | Prepara los datos, busca hiperparámetros con Optuna, compara Naive Bayes, regresión logística y XGBoost en paralelo, y registra el mejor en MLflow. | Cada 3 meses |
| [`phishing_champion_retrain`](airflow/dags/champion_training_dag.py) | Reentrena el modelo marcado como `champion`, conservando su algoritmo e hiperparámetros. | Mensual |

**Entrenamiento y comparación:** lee el CSV `data_*.csv` más reciente (por fecha
de subida) de `s3://data/datasets/raw/`,
limpia los correos y separa 70% para entrenamiento, 15% para validación y 15% para
test. Calcula un baseline heurístico como referencia y entrena los tres modelos
en paralelo. Cada modelo ejecuta una búsqueda de hiperparámetros con Optuna
(TPE, 3-fold CV sobre train) antes de ajustar el modelo final.
Elige el de mayor F1 de validación y lo evalúa sobre test.

Parámetros configurables al ejecutar manualmente:

| Parámetro | Por defecto | Descripción |
| --- | --- | --- |
| `simular_comparacion` | `false` | Suma ruido aleatorio al F1 de selección para probar distintos ganadores |
| `n_trials` | `30` | Número máximo de trials de Optuna por modelo |
| `patience` | `10` | Trials consecutivos sin mejora antes de detener la búsqueda |
| `min_trials` | `10` | Mínimo de trials antes de que el early stopping pueda activarse |

**Reentrenamiento:** carga el pipeline completo del `champion`, prepara el CSV
más reciente de esa misma ubicación en RustFS y vuelve a ajustar el
preprocesamiento y el modelo. Guarda los resultados en MLflow y registra una
nueva versión como `challenger`.

El entrenamiento trimestral corre el 1 de enero, abril, julio y octubre; el
reentrenamiento corre el día 1 de cada mes. Ambos a las 00:00 UTC, también admiten
ejecución manual y deben estar activados en Airflow. No se disparan entre sí.

### MLflow

Guarda parámetros, métricas y modelos con su preprocesamiento. El experimento
`phishing-comparison` reúne las comparaciones y `phishing-retraining` los reentrenamientos.
El modelo registrado se llama `phishing_detector` y utiliza dos aliases:

- `champion`: la versión elegida para las predicciones de la API.
- `challenger`: el nuevo candidato para revisar.

El primer ganador recibe ambos aliases. Después, los nuevos candidatos no
reemplazan automáticamente al `champion`: ese cambio se realiza desde MLflow.

#### Simulación para probar cambios de modelo

Al ejecutar manualmente `phishing_training`, se puede activar el parámetro
`simular_comparacion` (por defecto `false`). En este modo educativo, cada modelo
recibe una variación aleatoria entre -0,05 y +0,05 sobre su F1 de validación.
El resultado se limita al rango [0, 1] y se usa para elegir al ganador. Esto permite
que gane otro modelo aunque se use el mismo dataset; no garantiza un cambio en cada ejecución.

MLflow guarda `validation_f1` con el valor real, `selection_f1` con el valor usado
para seleccionar, `selection_noise` con la variación sorteada, `best_cv_f1` con el
mejor F1 de validación cruzada encontrado por Optuna y `optuna_trials_run` con la
cantidad de trials ejecutados (puede ser menor que `n_trials` si el early stopping
se activó). Los runs y la versión registrada llevan `selection_mode=simulation`.
El F1 de test sigue siendo real. Esta simulación prueba el flujo de cambio de
modelos, no demuestra una mejora.

Para probar el cambio en la API, revisar el nuevo `challenger` y asignarle
manualmente el alias `champion` en MLflow. Con `simular_comparacion=false`, también
en las ejecuciones programadas, se elige únicamente por el F1 real.

### FastAPI
Todos los endpoints, salvo `GET /`, exigen la cabecera `X-API-Key` con el valor de
`API_KEY` de `.env`. Sin ella, o con una clave incorrecta, devuelven HTTP 401.
La clave se genera con `openssl rand -hex 32` y debe tener al menos 32
caracteres; si falta, la API no arranca.

Recibe el texto del correo en `POST /predictions`, por ejemplo:

```json
{"email_text": "Please verify your account immediately"}
```

Devuelve HTTP 201 con la clasificación, la probabilidad de phishing, la versión
utilizada y el `prediction_id` asignado. El header `Location` apunta a
`/predictions/{prediction_id}`. Cada predicción se persiste en una base de datos
PostgreSQL junto con el texto del correo y los resultados.

`GET /predictions/{prediction_id}` devuelve la predicción guardada, con su
feedback y fecha de creación, sin el texto del correo. Si no existe, devuelve
HTTP 404.

Una vez recibida la predicción, se puede enviar feedback sobre su corrección con
`POST /predictions/{prediction_id}/feedback`:

```json
{"feedback": "OK"}
```

El valor debe ser `OK` (predicción correcta) o `NO` (predicción incorrecta).
Devuelve HTTP 204. Si el `prediction_id` no existe, devuelve HTTP 404.

Usa el `champion` de MLflow y carga la nueva versión cuando cambia ese alias.
Si el champion no está disponible, devuelve HTTP 503.
La documentación interactiva está en `http://localhost:8800/docs`; para probar
los endpoints, cargar la clave con el botón **Authorize**. Desde la terminal:

```console
curl -X POST http://localhost:8800/predictions \
  -H "X-API-Key: <API_KEY>" -H "Content-Type: application/json" \
  -d '{"email_text": "Please verify your account immediately"}'
```

Para cambiar la clave, editar `API_KEY` en `.env`, aplicar el cambio con
`docker compose up -d --no-deps fastapi` (un `restart` no recarga las variables)
y actualizarla en la extensión de Chrome.

## Ejecución local

Con el stack levantado, primero descargar el CSV a RustFS y ejecutar
`phishing_training` desde `http://localhost:8080` para crear el primer champion.
Luego se puede ejecutar `phishing_champion_retrain`. Para usar datos nuevos,
hay que actualizar antes el CSV mediante la descarga.
Los resultados se consultan en `http://localhost:5000`.

### Precondiciones
Tener Docker con Compose disponible. Copiar el archivo `.env.example` a `.env`
si todavía no existe y completar las credenciales; conservar el `.env` propio
al actualizar la branch.

Para descargar el dataset, completar `KAGGLE_API_TOKEN` en `.env` con el token
de Kaggle. Docker Compose lo expone como `AIRFLOW_VAR_KAGGLE_API_TOKEN`, que
permite al DAG leerlo con `Variable.get("KAGGLE_API_TOKEN")`. No hace falta crear
una Variable en la interfaz de Airflow; las variables definidas por entorno no
aparecen en esa pantalla.
Si se cambia el token con el stack levantado, aplicar el cambio con:

```console
docker compose up -d --no-deps airflow-apiserver airflow-scheduler airflow-dag-processor airflow-worker airflow-triggerer
```

Un `docker compose restart` no actualiza las variables de entorno.

Para probar esta branch por primera vez o después de cambios de dependencias,
reconstruir y levantar el stack (también funciona desde PowerShell):

```console
docker compose up -d --build
```

Después, ejecutar manualmente `download_dataset` y, cuando termine,
`phishing_training`. El entrenamiento encuentra automáticamente el último CSV;
no hace falta copiarlo ni renombrarlo. Probar `POST /predictions` desde
`http://localhost:8800/docs`. El reentrenamiento requiere que ya exista un
`champion` y puede ejecutarse después.

El servidor usa MLflow 3.17.0 y los clientes de Airflow y FastAPI usan 2.22.5.
Airflow y FastAPI comparten los rangos de las dependencias de los modelos.
La construcción de Airflow valida las dependencias con `pip check` y excluye
los providers de Google y Snowflake, que este proyecto no utiliza.

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
