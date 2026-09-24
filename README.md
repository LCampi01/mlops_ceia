# Ejecución
## Precondiciones
Copiar el archivo `.env.example` a `.env` y poner valores serios.

## Comandos
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

# Credenciales del stack

## Minio
* user: `secret-user`
* pass: `MINIO_SECRET_ACCESS_KEY` de `.env`

## Airflow
* user: `secret-user`
* pass: `_AIRFLOW_WWW_USER_PASSWORD` de `.env`

## MLflow
* user: `secret-user`
* pass: `MLFLOW_AUTH_ADMIN_PASSWORD` de `.env`
