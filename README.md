# MLOps CEIA

## Integrantes
* Tomás Abraham (a2602)
* Carlos Agustín Berdaguer (a2605)
* Lucas Ezequiel Campi (a2609)
* José Miguel Silva Pavón (a2415)

## Objetivo
Servir un modelo de detección de _spam_ en un stack de MLFlow / Airflow / FastAPI.

## Ejecución

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

### Minio
* user: `secret-user`
* pass: `MINIO_SECRET_ACCESS_KEY` de `.env`

### Airflow
* user: `secret-user`
* pass: `_AIRFLOW_WWW_USER_PASSWORD` de `.env`

### MLflow
* user: `secret-user`
* pass: `MLFLOW_AUTH_ADMIN_PASSWORD` de `.env`
