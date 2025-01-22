import joblib
import boto3
import tempfile
import numpy
import re
import gc
import logging
from typing import List

from config import Config
from exception.validation_error import ValidationError
from models.prescription import Drug
from utils import status, stringutils


def get_substance(drugs: List[Drug]):
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


def get_substance_by_drug_name(drug_names: list[str]):
    drugs_dict = {}
    drug_names_words = []

    if not drug_names:
        return drugs_dict

    logging.basicConfig()
    logger = logging.getLogger("noharm.backend")
    drug_names_words = [stringutils.prepare_drug_name(n) for n in drug_names]

    model_subst = _get_model("models/noharm-ml-subst.gz")
    token_subst = _get_model("models/noharm-tk-subst.gz")

    vector = token_subst.transform(drug_names_words)
    prediction = model_subst.predict(vector)
    probabilities = model_subst.predict_proba(vector).round(2)
    MIN_PROB = 0.35

    for idx, p in enumerate(prediction):
        subst_idx = numpy.where(model_subst.classes_ == p)[0][0]
        subst_prob = probabilities[idx][subst_idx]

        if subst_prob >= MIN_PROB:
            drugs_dict[drug_names[idx]] = p

        logger.debug(
            f"AI INFER SUBSTANCE {drug_names[idx]} - {drug_names_words[idx]} - {subst_prob} - {p}"
        )

    del model_subst, token_subst, vector, prediction, probabilities
    gc.collect()

    return drugs_dict


def _get_client():
    return boto3.client("s3")


def _get_model(model_name):
    client = _get_client()
    model = None

    with tempfile.TemporaryFile() as f:
        client.download_fileobj(Config.CACHE_BUCKET_NAME, model_name, f)
        f.seek(0)

        model = joblib.load(f)

    return model
