"""Predicciones con el pipeline marcado como champion en MLflow."""
import logging
import os
import uuid
from contextlib import asynccontextmanager
from threading import Lock

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
import mlflow
import mlflow.sklearn
import pandas as pd
from pydantic import BaseModel, Field
import sqlalchemy as sa


DB_URL = os.environ.get("DATABASE_URL")
if DB_URL is None:
    raise ValueError("DATABASE_URL environment variable is not set")

engine = sa.create_engine(DB_URL, pool_pre_ping=True)
metadata = sa.MetaData()
predictions_table = sa.Table(
    "predictions",
    metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("email_text", sa.Text, nullable=False),
    sa.Column("prediction_code", sa.Integer, nullable=False),
    sa.Column("label", sa.String, nullable=False),
    sa.Column("phishing_probability", sa.Float, nullable=False),
    sa.Column("model_version", sa.String, nullable=False),
    sa.Column("feedback", sa.String, sa.CheckConstraint("feedback IN ('OK', 'NO')"), nullable=True),
    sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Crea la tabla si no existe al arrancar el servidor.
    metadata.create_all(engine)
    yield


app = FastAPI(
    title="API de Detección de Phishing",
    description="Predicciones con el modelo champion de MLflow",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MODEL_NAME = "phishing_detector"
model_cache = None
version_cache = None
model_lock = Lock()
logger = logging.getLogger(__name__)


class EmailInput(BaseModel):
    email_text: str = Field(min_length=1, pattern=r"\S", description="Texto original del correo")


class FeedbackInput(BaseModel):
    feedback: str = Field(pattern=r"^(OK|NO)$", description="OK si la predicción fue correcta, NO si no lo fue")


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


@app.post("/predictions", status_code=201)
def predict(data: EmailInput, response: Response):
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
    except Exception as error:
        logger.exception("Error durante la predicción")
        raise HTTPException(status_code=500, detail="No se pudo procesar el correo") from error

    prediction_id = uuid.uuid4().hex
    label = {0: "Legítimo", 1: "Phishing"}[prediction]
    with engine.begin() as conn:
        conn.execute(predictions_table.insert().values(
            id=prediction_id,
            email_text=data.email_text,
            prediction_code=prediction,
            label=label,
            phishing_probability=round(probability, 4),
            model_version=version,
        ))

    response.headers["Location"] = f"/predictions/{prediction_id}"
    return {
        "prediction_id": prediction_id,
        "prediction_code": prediction,
        "label": label,
        "phishing_probability": round(probability, 4),
        "model_version": version,
    }


@app.get("/predictions/{prediction_id}")
def get_prediction(prediction_id: str):
    # Devuelve el resultado y su feedback.
    columns = [
        predictions_table.c.id.label("prediction_id"),
        predictions_table.c.prediction_code,
        predictions_table.c.label,
        predictions_table.c.phishing_probability,
        predictions_table.c.model_version,
        predictions_table.c.feedback,
        predictions_table.c.created_at,
    ]
    with engine.connect() as conn:
        row = conn.execute(
            sa.select(*columns).where(predictions_table.c.id == prediction_id)
        ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Predicción no encontrada")
    return dict(row)


@app.post("/predictions/{prediction_id}/feedback", status_code=204)
def feedback(prediction_id: str, data: FeedbackInput):
    with engine.begin() as conn:
        result = conn.execute(
            predictions_table.update()
            .where(predictions_table.c.id == prediction_id)
            .values(feedback=data.feedback)
        )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Predicción no encontrada")
