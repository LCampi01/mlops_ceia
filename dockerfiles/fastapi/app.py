#from fastapi import FastAPI


#app = FastAPI()


#@app.get("/")
#def read_root():
#    return {"message": "Welcome to the Model Service"}


# app.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import pandas as pd
import joblib
import os
from scipy.sparse import hstack, csr_matrix

app = FastAPI(
    title="API de Detección de Phishing",
    description="Servicio de inferencia en tiempo real usando XGBoost",
    version="1.0.0"
)

# Definir la ruta donde están guardados los modelos
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, 'models')

# Carga de artefactos al iniciar la aplicación
try:
    scaler_tfidf = joblib.load(os.path.join(MODELS_DIR, 'scaler_tfidf.joblib'))
    tf_transformer = joblib.load(os.path.join(MODELS_DIR, 'column_transformer.joblib'))
    model = joblib.load(os.path.join(MODELS_DIR, 'xgb_model.joblib'))
    print(" Artefactos cargados correctamente en la API.")
except Exception as e:
    print(f" Error al cargar los artefactos: {e}")


# Definimos la estructura de datos que la API espera recibir (JSON)
class EmailInput(BaseModel):
    # Variables de texto procesadas previamente (Vector TF-IDF de ejemplo)
    tfidf_vector: list[float]  
    
    # Variables numéricas y categóricas extra
    has_link: int                 # 0 o 1
    domain_dot_high: int          # 0 o 1
    has_suspicious_tags: int      # 0 o 1
    words_count_cat: str          # Categórica (ej: 'short', 'medium', 'long')
    imperative_verbs_count: int  # Conteo de verbos imperativos
    pronoun_density: float        # Densidad de pronombres (ej: 0.15)
    urgency_markers_count: int    # Conteo de palabras de urgencia


@app.get("/")
def home():
    return {
        "status": "online",
        "message": "Servicio de predicción de Phishing activo"
    }


@app.post("/predict")
def predict(data: EmailInput):
    try:
        # 1. Convertir las características extra a un DataFrame de pandas
        df_extra = pd.DataFrame([{
            'has_link': data.has_link,
            'domain_dot_high': data.domain_dot_high,
            'has_suspicious_tags': data.has_suspicious_tags,
            'words_count_cat': data.words_count_cat,
            'imperative_verbs_count': data.imperative_verbs_count,
            'pronoun_density': data.pronoun_density,
            'urgency_markers_count': data.urgency_markers_count
        }])

        # 2. Transformar las características extra con el ColumnTransformer cargado
        X_extra_transformed = tf_transformer.transform(df_extra)

        # 3. Convertir la lista TF-IDF a matriz dispersa y escalarla
        X_tfidf_sparse = csr_matrix([data.tfidf_vector])
        X_tfidf_scaled = scaler_tfidf.transform(X_tfidf_sparse)

        # 4. Concatenar horizontalmente ambos conjuntos de características
        X_final = hstack([X_tfidf_scaled, X_extra_transformed])

        # 5. Generar la predicción con XGBoost
        prediction = int(model.predict(X_final)[0])
        probability = float(model.predict_proba(X_final)[0][1])

        labels = {0: 'Legítimo', 1: 'Phishing'}

        return {
            "prediction_code": prediction,
            "label": labels.get(prediction, "Desconocido"),
            "phishing_probability": round(probability, 4)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error durante la inferencia: {str(e)}")
