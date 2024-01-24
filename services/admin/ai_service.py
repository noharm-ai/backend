import joblib
import boto3
import tempfile
import numpy

from config import Config
from models.main import *
from exception.validation_error import ValidationError


def get_substance(drugs: list[Drug]):
    if len(drugs) == 0:
        raise ValidationError(
            "Nenhum item selecionado",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    model_subst = _get_model("models/noharm-ml-subst.gz")
    token_subst = _get_model("models/noharm-tk-subst.gz")

    drugs_array = []

    drug_names = []
    for d in drugs:
        drug_names.append(d.name)

    vector = token_subst.transform(drug_names)

    prediction = model_subst.predict(vector)

    for idx, p in enumerate(prediction):
        subst_idx = numpy.where(model_subst.classes_ == p)[0][0]

        subst_prob = model_subst.predict_proba(vector).round(2)[idx][subst_idx]
        drugs_array.append(
            {
                "sctid": p,
                "idDrug": drugs[idx].id,
                "drug": drugs[idx].name,
                "accuracy": subst_prob * 100,
            }
        )

    return drugs_array


def _get_client():
    return boto3.client(
        "s3",
        aws_access_key_id=Config.CACHE_BUCKET_ID,
        aws_secret_access_key=Config.CACHE_BUCKET_KEY,
    )


def _get_model(model_name):
    client = _get_client()
    model = None

    with tempfile.TemporaryFile() as f:
        client.download_fileobj(Config.CACHE_BUCKET_NAME, model_name, f)
        f.seek(0)

        model = joblib.load(f)

    return model
