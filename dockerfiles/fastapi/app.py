"""Predicciones con el pipeline marcado como champion en MLflow."""
import logging
import os
from threading import Lock

from fastapi import FastAPI, HTTPException
import mlflow
import mlflow.sklearn
import pandas as pd
from pydantic import BaseModel, Field

app = FastAPI(
    title="API de Detección de Phishing",
    description="Predicciones con el modelo champion de MLflow",
    version="2.0.0",
)

MODEL_NAME = "phishing_detector"
model_cache = None
version_cache = None
model_lock = Lock()
logger = logging.getLogger(__name__)


class EmailInput(BaseModel):
    email_text: str = Field(min_length=1, pattern=r"\S", description="Texto original del correo")


def cargar_champion():
    global model_cache, version_cache
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"))
    # El lock evita descargar dos veces el modelo ante pedidos simultáneos.
    with model_lock:
        champion = mlflow.MlflowClient().get_model_version_by_alias(MODEL_NAME, "champion")
        version = str(champion.version)
        if model_cache is None or version != version_cache:
            # Cargar la versión resuelta: el alias podría cambiar durante la descarga.
            model = mlflow.sklearn.load_model(f"models:/{MODEL_NAME}/{version}")
            model_cache, version_cache = model, version
            logger.info("Champion cargado: versión %s", version)
        return model_cache, version_cache


@app.get("/")
def home():
    return {"status": "online", "message": "API de predicción de phishing"}


@app.post("/predict")
def predict(data: EmailInput):
    try:
        model, version = cargar_champion()
    except Exception as error:
        logger.exception("No se pudo cargar el champion desde MLflow")
        raise HTTPException(status_code=503, detail="El modelo champion no está disponible") from error

    try:
        # El pipeline registrado ya incluye limpieza, TF-IDF y atributos adicionales.
        emails = pd.DataFrame({"email_text": [data.email_text]})
        prediction = int(model.predict(emails)[0])
        phishing_column = list(model.classes_).index(1)
        probability = float(model.predict_proba(emails)[0][phishing_column])
        return {
            "prediction_code": prediction,
            "label": {0: "Legítimo", 1: "Phishing"}[prediction],
            "phishing_probability": round(probability, 4),
            "model_version": version,
        }
    except Exception as error:
        logger.exception("Error durante la predicción")
        raise HTTPException(status_code=500, detail="No se pudo procesar el correo") from error
