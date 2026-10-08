# MLOps CEIA

## Integrantes
* Tomás Abraham (a2602)
* Carlos Agustín Berdaguer (a2605)
* Lucas Ezequiel Campi (a2609)
* José Miguel Silva Pavón (a2415)

## Objetivo
Servir un modelo de detección de _spam_ en un stack de MLFlow / Airflow / FastAPI.

## Arquitectura

### DAGs de Airflow

| DAG | Qué hace | Frecuencia |
| --- | --- | --- |
| `download_dataset` | Descarga el dataset de phishing desde Kaggle y lo guarda en RustFS. Pendiente de integrar desde `feat-dataset-download`. | Manual |
| [`phishing_training`](airflow/dags/phishing_training_dag.py) | Prepara los datos, compara Naive Bayes, regresión logística y XGBoost, y registra el mejor en MLflow. | Cada 3 meses |
| [`phishing_champion_retrain`](airflow/dags/champion_training_dag.py) | Reentrena el modelo marcado como `champion`, conservando su algoritmo e hiperparámetros. | Mensual |

**Entrenamiento y comparación:** lee `s3://data/datasets/Phishing_Email.csv`,
limpia los correos y separa 70% para entrenamiento, 15% para validación y 15% para
test. Calcula un baseline heurístico como referencia y entrena los tres modelos.
Elige el de mayor F1 de validación y lo evalúa sobre test.

```text
preparar_datos → entrenar_modelos → registrar_mejor_modelo
```

**Reentrenamiento:** carga el pipeline completo del `champion`, prepara el CSV
actual de RustFS y vuelve a ajustar el preprocesamiento y el modelo. Guarda los
resultados en MLflow y registra una nueva versión como `challenger`.

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
para seleccionar y `selection_noise` con la variación sorteada. Los runs y la
versión registrada llevan `selection_mode=simulation`. El F1 de test sigue siendo
real. Esta simulación prueba el flujo de cambio de modelos, no demuestra una mejora.

Para probar el cambio en la API, revisar el nuevo `challenger` y asignarle
manualmente el alias `champion` en MLflow. Con `simular_comparacion=false`, también
en las ejecuciones programadas, se elige únicamente por el F1 real.

### FastAPI
Recibe el texto del correo en `POST /predict`, por ejemplo:

```json
{"email_text": "Please verify your account immediately"}
```

Usa el `champion` de MLflow y carga la nueva versión cuando cambia ese alias.
Devuelve la clasificación, la probabilidad de phishing y la versión utilizada.
Si el champion no está disponible, devuelve HTTP 503.
La documentación interactiva está en `http://localhost:8800/docs`.

## Ejecución local

Con el stack levantado, primero descargar el CSV a RustFS y ejecutar
`phishing_training` desde `http://localhost:8080` para crear el primer champion.
Luego se puede ejecutar `phishing_champion_retrain`. Para usar datos nuevos,
hay que actualizar antes el CSV mediante la descarga.
Los resultados se consultan en `http://localhost:5000`.

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
