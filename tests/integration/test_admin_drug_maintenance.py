"""Integration tests for the admin drug maintenance endpoints.

Three endpoints of the drug curation screen had no coverage. They are the tools
a curator uses to find and repair drugs the scoring pipeline cannot work with:

* ``GET /admin/drug/ref`` (``admin_drug_service.get_drug_ref``) — the curation
  notes stored on a substance, shown next to the drug being curated;
* ``GET /admin/drug/get-missing-substance``
  (``admin_drug_service.get_drugs_missing_substance``) — scored drugs that were
  never linked to a substance, the worklist of the curation screen;
* ``POST /admin/drug/add-new-outlier``
  (``admin_drug_service.add_new_drugs_to_outlier``) — backfills a placeholder
  outlier row for drugs prescribed in the last five days that the pipeline has
  never seen, so they start being scored.

Fixtures use the reserved ``>= 90000`` id range (91400 block) so the
session-scoped ``clean_test_artifacts`` fixture removes them. The outlier rows
``add-new-outlier`` creates take their id from the table sequence, so they fall
outside that range and are removed by id watermark instead.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)

REF_URL = "/admin/drug/ref"
MISSING_SUBSTANCE_URL = "/admin/drug/get-missing-substance"
ADD_OUTLIER_URL = "/admin/drug/add-new-outlier"

_SEGMENT = 1

# ids reserved for this module
_SUBSTANCE_WITH_REF = 9140001
_SUBSTANCE_WITHOUT_REF = 9140002
_UNKNOWN_SUBSTANCE = 9140099

_NAME_WITH_REF = "ZZTEST ADMIN SUBSTANCIA CURADA"
_NAME_WITHOUT_REF = "ZZTEST ADMIN SUBSTANCIA SEM CURADORIA"
_REF_TEXT = "Ajustar dose na insuficiência renal."

_DRUG_MISSING_SUBSTANCE = 91401  # scored, no sctid -> shows up in the worklist
_DRUG_WITH_SUBSTANCE = 91402  # scored and linked -> already curated
_DRUG_UNSCORED = 91403  # no sctid, but no outlier either
_DRUG_PRESCRIBED_NOW = 91404  # prescribed today, never scored
_DRUG_PRESCRIBED_LONG_AGO = 91405  # prescribed outside the five-day window


@pytest.fixture
def curation_substances():
    """Two substances: one with curation notes, one without."""
    for sctid, name, ref in (
        (_SUBSTANCE_WITH_REF, _NAME_WITH_REF, _REF_TEXT),
        (_SUBSTANCE_WITHOUT_REF, _NAME_WITHOUT_REF, None),
    ):
        session.execute(
            text(
                "INSERT INTO public.substancia (sctid, nome, link, ativo, curadoria) "
                "VALUES (:sctid, :name, '', true, :ref)"
            ),
            {"sctid": sctid, "name": name, "ref": ref},
        )
    session_commit()

    yield

    session.execute(text("DELETE FROM public.substancia WHERE sctid >= 9140000"))
    session_commit()


@pytest.fixture
def curation_drugs(curation_substances):  # noqa: ARG001
    """Drugs covering the curated / uncurated / unscored combinations."""
    for id_drug, name, sctid in (
        (_DRUG_MISSING_SUBSTANCE, "ZZTEST ADMIN SEM SUBSTANCIA", None),
        (_DRUG_WITH_SUBSTANCE, "ZZTEST ADMIN COM SUBSTANCIA", _SUBSTANCE_WITH_REF),
        (_DRUG_UNSCORED, "ZZTEST ADMIN SEM OUTLIER", None),
    ):
        session.execute(
            text(
                "INSERT INTO demo.medicamento (fkmedicamento, fkhospital, nome, sctid) "
                "VALUES (:id, 1, :name, :sctid)"
            ),
            {"id": id_drug, "name": name, "sctid": sctid},
        )

    for id_drug in (_DRUG_MISSING_SUBSTANCE, _DRUG_WITH_SUBSTANCE):
        session.execute(
            text(
                "INSERT INTO demo.outlier "
                "(fkmedicamento, idsegmento, contagem, doseconv, frequenciadia, escore) "
                "VALUES (:id, :segment, 10, 1, 1, 1)"
            ),
            {"id": id_drug, "segment": _SEGMENT},
        )
    session_commit()

    yield

    session.execute(text("DELETE FROM demo.outlier WHERE fkmedicamento >= 90000"))
    session.execute(text("DELETE FROM demo.medicamento WHERE fkmedicamento >= 90000"))
    session_commit()


def _prescribe(id_drug: int, days_ago: int):
    """Prescribe ``id_drug`` once, ``days_ago`` before now.

    ``add_new_drugs_to_outlier`` selects on ``prescricao.update_at``, so the
    prescription is aged on that column as well as on its date.
    """
    id_prescription = test_counters["id_prescription"]
    admission_number = test_counters["admission_number"]
    test_counters["id_prescription"] += 1
    test_counters["admission_number"] += 1

    date = datetime.now() - timedelta(days=days_ago)

    create_prescription(
        id=id_prescription,
        admissionNumber=admission_number,
        idPatient=id_prescription,
        idSegment=_SEGMENT,
        date=date,
        expire=date + timedelta(days=1),
    )
    # `<prescription id>001`, above the 100000001 presmed cleanup threshold
    create_prescription_drug(
        id=int(f"{id_prescription}001"),
        idPrescription=id_prescription,
        idDrug=id_drug,
        idSegment=_SEGMENT,
    )

    session.execute(
        text("UPDATE demo.prescricao SET update_at = :date WHERE fkprescricao = :id"),
        {"date": date, "id": id_prescription},
    )
    session_commit()

    return id_prescription


@pytest.fixture
def prescribed_drugs():
    """Two never-scored drugs, one prescribed today and one two weeks ago."""
    for id_drug, name in (
        (_DRUG_PRESCRIBED_NOW, "ZZTEST ADMIN PRESCRITO AGORA"),
        (_DRUG_PRESCRIBED_LONG_AGO, "ZZTEST ADMIN PRESCRITO ANTES"),
    ):
        session.execute(
            text(
                "INSERT INTO demo.medicamento (fkmedicamento, fkhospital, nome) "
                "VALUES (:id, 1, :name)"
            ),
            {"id": id_drug, "name": name},
        )
    session_commit()

    _prescribe(_DRUG_PRESCRIBED_NOW, days_ago=0)
    _prescribe(_DRUG_PRESCRIBED_LONG_AGO, days_ago=14)

    # rows the endpoint creates get a sequence id, so remember the watermark
    watermark = session.execute(
        text("SELECT coalesce(max(idoutlier), 0) FROM demo.outlier")
    ).scalar()

    yield

    session.execute(
        text("DELETE FROM demo.outlier WHERE idoutlier > :watermark"),
        {"watermark": watermark},
    )
    session.execute(text("DELETE FROM demo.medicamento WHERE fkmedicamento >= 90000"))
    session_commit()


def _data(response):
    """Payload of a successful response."""
    return response.get_json()["data"]


def _outlier_count(id_drug: int) -> int:
    """Outlier rows currently stored for a drug."""
    session_commit()
    return session.execute(
        text("SELECT count(*) FROM demo.outlier WHERE fkmedicamento = :id"),
        {"id": id_drug},
    ).scalar()


# --- GET /admin/drug/ref -------------------------------------------------------


def test_ref_no_token(client):
    """GET /admin/drug/ref — 401 without authentication."""
    response = client.get(f"{REF_URL}?sctid={_SUBSTANCE_WITH_REF}")

    assert response.status_code == 401


def test_ref_permission_denied(client, analyst_headers):
    """GET /admin/drug/ref — 401 for a role without ADMIN_DRUGS."""
    response = client.get(
        f"{REF_URL}?sctid={_SUBSTANCE_WITH_REF}", headers=analyst_headers
    )

    assert response.status_code == 401


def test_ref_returns_curation_text(client, admin_headers, curation_substances):
    """The substance name and its curation notes come back together."""
    response = client.get(
        f"{REF_URL}?sctid={_SUBSTANCE_WITH_REF}", headers=admin_headers
    )

    assert response.status_code == 200
    assert _data(response) == {"name": _NAME_WITH_REF, "ref": _REF_TEXT}


def test_ref_without_curation_text(client, admin_headers, curation_substances):
    """A substance nobody curated yet resolves with an empty ref."""
    response = client.get(
        f"{REF_URL}?sctid={_SUBSTANCE_WITHOUT_REF}", headers=admin_headers
    )

    assert response.status_code == 200
    assert _data(response) == {"name": _NAME_WITHOUT_REF, "ref": None}


def test_ref_unknown_substance(client, admin_headers):
    """An sctid with no substance behind it is rejected [400]."""
    response = client.get(f"{REF_URL}?sctid={_UNKNOWN_SUBSTANCE}", headers=admin_headers)

    assert response.status_code == 400


def test_ref_without_sctid(client, admin_headers):
    """Omitting sctid is rejected the same way as an unknown one [400]."""
    response = client.get(REF_URL, headers=admin_headers)

    assert response.status_code == 400


# --- GET /admin/drug/get-missing-substance -------------------------------------


def test_missing_substance_no_token(client):
    """GET /admin/drug/get-missing-substance — 401 without authentication."""
    response = client.get(MISSING_SUBSTANCE_URL)

    assert response.status_code == 401


def test_missing_substance_permission_denied(client, analyst_headers):
    """GET /admin/drug/get-missing-substance — 401 without ADMIN_DRUGS."""
    response = client.get(MISSING_SUBSTANCE_URL, headers=analyst_headers)

    assert response.status_code == 401


def test_missing_substance_lists_scored_drugs_only(
    client, admin_headers, curation_drugs
):
    """Only drugs that are scored *and* unlinked belong to the worklist."""
    response = client.get(MISSING_SUBSTANCE_URL, headers=admin_headers)

    assert response.status_code == 200
    id_drugs = _data(response)

    assert _DRUG_MISSING_SUBSTANCE in id_drugs
    # already linked to a substance
    assert _DRUG_WITH_SUBSTANCE not in id_drugs
    # unlinked, but the pipeline never scored it, so there is nothing to fix
    assert _DRUG_UNSCORED not in id_drugs


def test_missing_substance_is_sorted_and_unique(client, admin_headers, curation_drugs):
    """Drug ids come back ascending and without repetitions."""
    response = client.get(MISSING_SUBSTANCE_URL, headers=admin_headers)

    assert response.status_code == 200
    id_drugs = _data(response)

    assert id_drugs == sorted(id_drugs)
    assert len(id_drugs) == len(set(id_drugs))


# --- POST /admin/drug/add-new-outlier ------------------------------------------


def test_add_new_outlier_no_token(client):
    """POST /admin/drug/add-new-outlier — 401 without authentication."""
    response = client.post(ADD_OUTLIER_URL)

    assert response.status_code == 401


def test_add_new_outlier_permission_denied(client, analyst_headers):
    """POST /admin/drug/add-new-outlier — 401 without ADMIN_DRUGS."""
    response = client.post(ADD_OUTLIER_URL, headers=analyst_headers)

    assert response.status_code == 401


def test_add_new_outlier_backfills_recent_drugs(
    client, admin_headers, prescribed_drugs
):
    """A drug prescribed inside the five-day window gets a placeholder outlier."""
    assert _outlier_count(_DRUG_PRESCRIBED_NOW) == 0

    response = client.post(ADD_OUTLIER_URL, headers=admin_headers)

    assert response.status_code == 200
    # the response is the number of rows the backfill inserted
    assert _data(response) >= 1
    assert _outlier_count(_DRUG_PRESCRIBED_NOW) == 1


def test_add_new_outlier_skips_old_prescriptions(
    client, admin_headers, prescribed_drugs
):
    """A drug last prescribed outside the window is left alone."""
    response = client.post(ADD_OUTLIER_URL, headers=admin_headers)

    assert response.status_code == 200
    assert _outlier_count(_DRUG_PRESCRIBED_LONG_AGO) == 0


def test_add_new_outlier_placeholder_shape(client, admin_headers, prescribed_drugs):
    """The placeholder carries the prescription segment and a neutral score."""
    client.post(ADD_OUTLIER_URL, headers=admin_headers)
    session_commit()

    row = session.execute(
        text(
            "SELECT idsegmento, contagem, doseconv, frequenciadia, escore "
            "FROM demo.outlier WHERE fkmedicamento = :id"
        ),
        {"id": _DRUG_PRESCRIBED_NOW},
    ).first()

    # score 4 is the neutral value the pipeline replaces once it has history
    assert tuple(row) == (_SEGMENT, 0, 0, 0, 4)


def test_add_new_outlier_is_idempotent(client, admin_headers, prescribed_drugs):
    """Running the backfill twice does not duplicate a drug's placeholder."""
    client.post(ADD_OUTLIER_URL, headers=admin_headers)
    session_commit()

    response = client.post(ADD_OUTLIER_URL, headers=admin_headers)

    assert response.status_code == 200
    assert _outlier_count(_DRUG_PRESCRIBED_NOW) == 1
