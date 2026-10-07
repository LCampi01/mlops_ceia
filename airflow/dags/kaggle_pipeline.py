import os
import zipfile

KAGGLE_DATASET = "subhajournal/phishingemails"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASETS_DIR = os.path.join(BASE_DIR, "datasets")
RAW_CSV = os.path.join(DATASETS_DIR, "Phishing_Email.csv")

def download_dataset() -> str:
    import kaggle
    if not os.environ.get("KAGGLE_API_TOKEN"):
        raise EnvironmentError(
            "No se encontraron las credenciales de Kaggle. "
            "Configurar variable de entorno KAGGLE_API_TOKEN."
        )
    os.makedirs(DATASETS_DIR, exist_ok=True)
    print(f"Descargando dataset '{KAGGLE_DATASET}' en '{DATASETS_DIR}'.")
    kaggle.api.authenticate()
    kaggle.api.dataset_download_files(
        KAGGLE_DATASET,
        path=DATASETS_DIR,
        unzip=False,
        quiet=False,
    )
    zip_name = KAGGLE_DATASET.split("/")[-1] + ".zip"
    zip_path = os.path.join(DATASETS_DIR, zip_name)
    print(f"Descomprimiendo '{zip_path}'.")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(DATASETS_DIR)
    os.remove(zip_path)
    if not os.path.exists(RAW_CSV):
        extracted = os.listdir(DATASETS_DIR)
        raise FileNotFoundError(
            f"No se pudo encontrar '{RAW_CSV}'."
            f"Archivos encontrados: {extracted}"
        )

    print(f"Dataset listo en '{RAW_CSV}'.")
    return RAW_CSV
