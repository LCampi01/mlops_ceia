# train_pipeline.py
from datetime import datetime
import os
import joblib
import pandas as pd
from scipy.sparse import load_npz, hstack
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.metrics import confusion_matrix, precision_score, recall_score, f1_score
from xgboost import XGBClassifier

BASE_DIR = os.path.dirname(os.path.abspath(__file__))   # Ruta de la carpeta donde vive este script (/opt/airflow/dags)
DATASETS_DIR = os.path.join(BASE_DIR, 'datasets')       # Apunta a /opt/airflow/dags/datasets
MODELS_DIR = os.path.join(BASE_DIR, 'models')           # Guarda en /opt/airflow/dags/models

def run_training_pipeline():
    os.makedirs(MODELS_DIR, exist_ok=True)
    
    # 1. Carga de datos
    X_train = load_npz(DATASETS_DIR/X_train.npz')
    X_test = load_npz(DATASETS_DIR/X_test.npz')
    X_extra_train = pd.read_csv(DATASETS_DIR/X_extra_train.csv')
    X_extra_test = pd.read_csv(DATASETS_DIR/X_extra_test.csv')
    y_train = pd.read_csv(DATASETS_DIR/y_train.csv')['label']
    y_test = pd.read_csv(DATASETS_DIR/y_test.csv')['label']

    # 2. Preprocesamiento
    ohe = OneHotEncoder(drop='first', handle_unknown='ignore')
    scaler_num = StandardScaler(with_mean=False)
    scaler_tfidf = StandardScaler(with_mean=False)

    tf = ColumnTransformer(transformers=[
        ('bin', 'passthrough', ['has_link', 'domain_dot_high', 'has_suspicious_tags']),
        ('cat', ohe, ['words_count_cat']),
        ('num', scaler_num, ['imperative_verbs_count', 'pronoun_density', 'urgency_markers_count'])
    ], remainder='drop')

    X_train = scaler_tfidf.fit_transform(X_train)
    X_test = scaler_tfidf.transform(X_test)

    X_extra_train = tf.fit_transform(X_extra_train)
    X_extra_test = tf.transform(X_extra_test)

    X_train_final = hstack([X_train, X_extra_train])
    X_test_final = hstack([X_test, X_extra_test])

    # 3. Entrenamiento
    xgb_model = XGBClassifier(
        objective='binary:logistic',
        eval_metric='logloss',
        random_state=42,
        n_estimators=200,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.9,
        reg_lambda=1
    )

    xgb_model.fit(X_train_final, y_train)

    # 4. Evaluación básica
    y_pred = xgb_model.predict(X_test_final)
    f1 = f1_score(y_test, y_pred)
    print(f"Entrenamiento completado. F1-Score: {f1:.4f}")

    # 5. Exportar artefactos para la API
    joblib.dump(scaler_tfidf, f'{MODELS_DIR}/scaler_tfidf.joblib')
    joblib.dump(tf, f'{MODELS_DIR}/column_transformer.joblib')
    joblib.dump(xgb_model, f'{MODELS_DIR}/xgb_model.joblib')
    print("Artefactos guardados exitosamente.")

if __name__ == '__main__':
    run_training_pipeline()