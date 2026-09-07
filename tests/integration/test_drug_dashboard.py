"""Integration tests for the drug dashboard endpoint.

``GET /drugs/dashboard/<segment>/<drug>`` (``drug_service.get_drug_dashboard``)
is the screen a pharmacist opens from a prescription line to see how the drug
behaves in that segment: the substance reference, the segment attributes, every
dose/frequency pair already scored for it (``outlier``) and the unit
conversions configured for the segment.

The endpoint had no coverage, and it is not a plain read:

* it answers with a *stub* payload (drug name only) when the drug has no
  substance linked yet, which is how the front end knows to send the user to
  the curation screen first;
* the segment attributes row is optional, so every attribute-derived field of
  the response has a fallback;
* when the caller passes ``dose`` and ``frequency`` (the prescribed values) the
  matching outlier is flagged ``selected``, and when no outlier matches, one is
  *created* with score 4 so the pair shows up on the dashboard from then on.
  That write is the reason this is an integration test: it has to be observed
  in the database, not only in the response.

Fixtures use the reserved ``>= 90000`` id range (90700 block) so the
session-scoped ``clean_test_artifacts`` fixture removes anything left behind;
rows created inside that range by the endpoint itself are dropped on teardown
as well, since other modules in the same session share the seed.
"""

import pytest
from sqlalchemy import bindparam, text

from tests.conftest import session, session_commit
from utils import status

URL = "/drugs/dashboard"

# demo.segmento seed rows
_SEGMENT_ADULT = 1
_SEGMENT_CPOE = 2

# Ids reserved for this module (90700 block, distinct from other modules').
_SCTID = 90701

_DRUG_FULL = 90701  # substance + attributes + outliers + conversions
_DRUG_NO_SUBSTANCE = 90702  # no sctid, so the stub payload is returned
_DRUG_NO_ATTRIBUTES = 90703  # substance, but no medatributos on the segment
_DRUG_CREATES = 90704  # target of the "unseen pair is created" test
_DRUG_ROUNDS = 90705  # target of the dose-rounding test
_DRUG_IGNORES = 90706  # target of the invalid/partial parameter tests
_UNKNOWN_DRUG = 90799

_DRUG_IDS = (
    _DRUG_FULL,
    _DRUG_NO_SUBSTANCE,
    _DRUG_NO_ATTRIBUTES,
    _DRUG_CREATES,
    _DRUG_ROUNDS,
    _DRUG_IGNORES,
)

# outlier ids, ordered here as the endpoint should return them:
# countNum desc, then frequency asc
_OUTLIER_TOP = 90701  # count 50, freq 1
_OUTLIER_SECOND = 90702  # count 50, freq 2
_OUTLIER_LAST = 90703  # count 10, freq 33 -> labelled "SN"
_OUTLIER_NO_ATTRIBUTES = 90704  # belongs to _DRUG_NO_ATTRIBUTES

_NOTE_TEXT = "ZZTest observacao do outlier"

# seed demo.unidademedida rows
_UNIT_ATTRIBUTES = "1"
_UNIT_CONVERSION = "2"
_UNIT_OTHER_SEGMENT = "4"

# the demo user behind the analyst_headers fixture
CALLER_ID = 1


@pytest.fixture(scope="module", autouse=True)
def seed_dashboard_data(clean_test_artifacts):  # noqa: ARG001
    """Substance, drugs, attributes, outliers and conversions for the dashboard."""
    session.execute(
        text(
            "INSERT INTO public.substancia "
            "(sctid, nome, link, ativo, unidadepadrao, divisor_faixa) "
            "VALUES (:id, 'ZZTest Substancia Dashboard', '', true, 'mg', 2.5)"
        ),
        {"id": _SCTID},
    )

    for id_drug, name, sctid in (
        (_DRUG_FULL, "ZZTest Medicamento Dashboard", _SCTID),
        (_DRUG_NO_SUBSTANCE, "ZZTest Medicamento Sem Substancia", None),
        (_DRUG_NO_ATTRIBUTES, "ZZTest Medicamento Sem Atributos", _SCTID),
        (_DRUG_CREATES, "ZZTest Medicamento Novo Outlier", _SCTID),
        (_DRUG_ROUNDS, "ZZTest Medicamento Arredonda", _SCTID),
        (_DRUG_IGNORES, "ZZTest Medicamento Ignora", _SCTID),
    ):
        session.execute(
            text(
                "INSERT INTO demo.medicamento (fkhospital, fkmedicamento, nome, sctid) "
                "VALUES (1, :id, :name, :sctid)"
            ),
            {"id": id_drug, "name": name, "sctid": sctid},
        )

    # _DRUG_NO_ATTRIBUTES is deliberately left without a medatributos row
    for id_drug in (
        _DRUG_FULL,
        _DRUG_NO_SUBSTANCE,
        _DRUG_CREATES,
        _DRUG_ROUNDS,
        _DRUG_IGNORES,
    ):
        session.execute(
            text(
                "INSERT INTO demo.medatributos "
                "(fkmedicamento, idsegmento, fkunidademedida, divisor, usapeso) "
                "VALUES (:id, :segment, :unit, 5, true)"
            ),
            {"id": id_drug, "segment": _SEGMENT_ADULT, "unit": _UNIT_ATTRIBUTES},
        )

    for id_outlier, id_drug, count, dose, frequency, score, manual_score in (
        (_OUTLIER_TOP, _DRUG_FULL, 50, 100, 1, 1, None),
        (_OUTLIER_SECOND, _DRUG_FULL, 50, 200, 2, 3, 2),
        (_OUTLIER_LAST, _DRUG_FULL, 10, 300, 33, 2, None),
        (_OUTLIER_NO_ATTRIBUTES, _DRUG_NO_ATTRIBUTES, 7, 400, 1, 4, None),
    ):
        session.execute(
            text(
                "INSERT INTO demo.outlier "
                "(idoutlier, fkmedicamento, idsegmento, contagem, doseconv, "
                "frequenciadia, escore, escoremanual, update_at, update_by) "
                "VALUES (:id_outlier, :id_drug, :segment, :count, :dose, "
                ":frequency, :score, :manual_score, "
                "'2025-01-02 03:04:05', :caller)"
            ),
            {
                "id_outlier": id_outlier,
                "id_drug": id_drug,
                "segment": _SEGMENT_ADULT,
                "count": count,
                "dose": dose,
                "frequency": frequency,
                "score": score,
                "manual_score": manual_score,
                "caller": CALLER_ID,
            },
        )

    # only the least prescribed outlier carries a note
    session.execute(
        text(
            "INSERT INTO demo.observacao "
            "(idoutlier, fkpresmed, nratendimento, idsegmento, fkmedicamento, text) "
            "VALUES (:id_outlier, 0, 1, :segment, :id_drug, :text)"
        ),
        {
            "id_outlier": _OUTLIER_LAST,
            "segment": _SEGMENT_ADULT,
            "id_drug": _DRUG_FULL,
            "text": _NOTE_TEXT,
        },
    )

    # one conversion on the requested segment and one on another, to assert the
    # response is restricted to the segment being viewed
    for id_segment, id_measure_unit, factor in (
        (_SEGMENT_ADULT, _UNIT_CONVERSION, 0.5),
        (_SEGMENT_CPOE, _UNIT_OTHER_SEGMENT, 0.001),
    ):
        session.execute(
            text(
                "INSERT INTO demo.unidadeconverte "
                "(fkmedicamento, idsegmento, fkunidademedida, fator) "
                "VALUES (:id_drug, :segment, :unit, :factor)"
            ),
            {
                "id_drug": _DRUG_FULL,
                "segment": id_segment,
                "unit": id_measure_unit,
                "factor": factor,
            },
        )

    session_commit()

    yield

    session.execute(text("DELETE FROM demo.observacao WHERE idoutlier >= 90700"))
    for table in ("outlier", "unidadeconverte", "medatributos", "medicamento"):
        session.execute(
            text(f"DELETE FROM demo.{table} WHERE fkmedicamento IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": list(_DRUG_IDS)},
        )
    session.execute(
        text("DELETE FROM public.substancia WHERE sctid = :id"), {"id": _SCTID}
    )
    session_commit()


def _get(client, headers, id_drug, id_segment=_SEGMENT_ADULT, **params):
    """Call the dashboard for one drug/segment pair."""
    query = "&".join(f"{key}={value}" for key, value in params.items())
    url = f"{URL}/{id_segment}/{id_drug}"

    return client.get(f"{url}?{query}" if query else url, headers=headers)


def _outliers(response):
    """Outlier rows of the response, in response order."""
    return response.get_json()["data"]["outliers"]


def _count_outliers(id_drug):
    """How many outlier rows the drug has on the adult segment."""
    return session.execute(
        text(
            "SELECT count(*) FROM demo.outlier "
            "WHERE fkmedicamento = :id_drug AND idsegmento = :segment"
        ),
        {"id_drug": id_drug, "segment": _SEGMENT_ADULT},
    ).scalar()


def test_drug_dashboard_permission_denied(client, config_manager_headers):
    """Teste get /drugs/dashboard - Deve negar acesso sem READ_PRESCRIPTION [401]"""
    response = _get(client, config_manager_headers, _DRUG_FULL)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_drug_dashboard_unknown_drug_is_rejected(client, analyst_headers):
    """Teste get /drugs/dashboard - Medicamento inexistente deve ser recusado [400]"""
    response = _get(client, analyst_headers, _UNKNOWN_DRUG)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidRecord"


def test_drug_dashboard_without_substance_returns_stub(client, analyst_headers):
    """Teste get /drugs/dashboard - Sem substância, retorna apenas o medicamento"""
    response = _get(client, analyst_headers, _DRUG_NO_SUBSTANCE)

    assert response.status_code == status.HTTP_200_OK

    data = response.get_json()["data"]
    # the front end uses the missing substance to require curation first, so
    # the attribute/outlier/conversion blocks must not be there at all
    assert data == {
        "drug": {
            "idDrug": _DRUG_NO_SUBSTANCE,
            "name": "ZZTest Medicamento Sem Substancia",
        },
        "substance": None,
    }


def test_drug_dashboard_payload_shape(client, analyst_headers):
    """Teste get /drugs/dashboard - Deve retornar medicamento, substância e atributos"""
    response = _get(client, analyst_headers, _DRUG_FULL)

    assert response.status_code == status.HTTP_200_OK

    data = response.get_json()["data"]
    assert set(data.keys()) == {
        "drug",
        "substance",
        "attributes",
        "outliers",
        "conversions",
    }
    assert data["drug"] == {
        "idDrug": _DRUG_FULL,
        "name": "ZZTest Medicamento Dashboard",
    }
    assert data["substance"] == {
        "name": "ZZTest Substancia Dashboard",
        "sctid": str(_SCTID),
        "idMeasureUnit": "mg",
        "divisionRange": 2.5,
    }
    assert data["attributes"] == {
        "divisionRange": 5,
        "idMeasureUnit": _UNIT_ATTRIBUTES,
        "useWeight": True,
    }


def test_drug_dashboard_attributes_fall_back_when_segment_has_no_row(
    client, analyst_headers
):
    """Teste get /drugs/dashboard - Sem medatributos no segmento, usa valores padrão"""
    response = _get(client, analyst_headers, _DRUG_NO_ATTRIBUTES)

    assert response.status_code == status.HTTP_200_OK

    data = response.get_json()["data"]
    assert data["attributes"] == {
        "divisionRange": None,
        "idMeasureUnit": None,
        "useWeight": False,
    }
    # the same fallback has to reach the outlier rows
    assert data["outliers"][0]["unit"] is None
    assert data["outliers"][0]["divisionRange"] is None
    assert data["outliers"][0]["useWeight"] is False


def test_drug_dashboard_outliers_ordered_by_count_then_frequency(
    client, analyst_headers
):
    """Teste get /drugs/dashboard - Outliers ordenados por contagem desc e frequência asc"""
    response = _get(client, analyst_headers, _DRUG_FULL)

    assert [o["idOutlier"] for o in _outliers(response)] == [
        _OUTLIER_TOP,
        _OUTLIER_SECOND,
        _OUTLIER_LAST,
    ]


def test_drug_dashboard_outlier_row_shape(client, analyst_headers):
    """Teste get /drugs/dashboard - Deve expor escore, observação e atributos do outlier"""
    rows = {
        o["idOutlier"]: o for o in _outliers(_get(client, analyst_headers, _DRUG_FULL))
    }

    assert rows[_OUTLIER_SECOND] == {
        "idOutlier": _OUTLIER_SECOND,
        "idDrug": _DRUG_FULL,
        "countNum": 50,
        "dose": 200,
        "unit": _UNIT_ATTRIBUTES,
        "frequency": 2,
        "score": 3,
        "manualScore": 2,
        "obs": "",
        "divisionRange": 5,
        "useWeight": True,
        "updatedAt": "2025-01-02T03:04:05",
        "selected": False,
    }
    # the note is joined by outlier, so only the annotated row carries it
    assert rows[_OUTLIER_LAST]["obs"] == _NOTE_TEXT
    # special frequencies are translated to their label
    assert rows[_OUTLIER_LAST]["frequency"] == "SN"


def test_drug_dashboard_conversions_limited_to_requested_segment(
    client, analyst_headers
):
    """Teste get /drugs/dashboard - Conversões devem ser apenas do segmento consultado"""
    response = _get(client, analyst_headers, _DRUG_FULL)

    assert response.get_json()["data"]["conversions"] == [
        {"idMeasureUnit": _UNIT_CONVERSION, "name": "mcg", "factor": 0.5}
    ]


def test_drug_dashboard_marks_prescribed_pair_as_selected(client, analyst_headers):
    """Teste get /drugs/dashboard - Dose e frequência prescritas marcam o outlier existente"""
    before = _count_outliers(_DRUG_FULL)

    response = _get(client, analyst_headers, _DRUG_FULL, dose=200, frequency=2)

    selected = [o["idOutlier"] for o in _outliers(response) if o["selected"]]
    assert selected == [_OUTLIER_SECOND]
    # an existing pair must not add a row
    assert _count_outliers(_DRUG_FULL) == before


def test_drug_dashboard_creates_outlier_for_unknown_pair(client, analyst_headers):
    """Teste get /drugs/dashboard - Par dose/frequência inédito deve gerar outlier escore 4"""
    assert _count_outliers(_DRUG_CREATES) == 0

    response = _get(client, analyst_headers, _DRUG_CREATES, dose=75, frequency=4)

    assert response.status_code == status.HTTP_200_OK

    rows = _outliers(response)
    assert len(rows) == 1
    assert rows[0]["dose"] == 75
    assert rows[0]["frequency"] == 4
    assert rows[0]["countNum"] == 1
    assert rows[0]["score"] == 4
    assert rows[0]["manualScore"] is None
    assert rows[0]["selected"] is True

    # the new pair is persisted, so the next prescription of it is not "new"
    stored = session.execute(
        text(
            "SELECT idoutlier, contagem, doseconv, frequenciadia, escore, update_by "
            "FROM demo.outlier "
            "WHERE fkmedicamento = :id_drug AND idsegmento = :segment"
        ),
        {"id_drug": _DRUG_CREATES, "segment": _SEGMENT_ADULT},
    ).fetchall()
    assert len(stored) == 1
    assert stored[0][0] == rows[0]["idOutlier"]
    assert (stored[0][1], stored[0][2], stored[0][3], stored[0][4]) == (1, 75, 4, 4)
    assert stored[0][5] == CALLER_ID


def test_drug_dashboard_rounds_created_dose_to_two_decimals(client, analyst_headers):
    """Teste get /drugs/dashboard - Dose do novo outlier é arredondada em duas casas"""
    response = _get(client, analyst_headers, _DRUG_ROUNDS, dose=12.3456, frequency=1)

    assert response.status_code == status.HTTP_200_OK
    assert _outliers(response)[0]["dose"] == 12.35

    stored_dose = session.execute(
        text(
            "SELECT doseconv FROM demo.outlier "
            "WHERE fkmedicamento = :id_drug AND idsegmento = :segment"
        ),
        {"id_drug": _DRUG_ROUNDS, "segment": _SEGMENT_ADULT},
    ).scalar()
    assert stored_dose == pytest.approx(12.35)


@pytest.mark.parametrize(
    "params",
    [
        {"dose": "abc", "frequency": 1},
        {"dose": 10, "frequency": "abc"},
        {"dose": 10},
        {"frequency": 1},
    ],
    ids=["invalid dose", "invalid frequency", "frequency missing", "dose missing"],
)
def test_drug_dashboard_ignores_unusable_dose_frequency(
    client, analyst_headers, params
):
    """Teste get /drugs/dashboard - Dose ou frequência inválida não gera outlier"""
    response = _get(client, analyst_headers, _DRUG_IGNORES, **params)

    assert response.status_code == status.HTTP_200_OK
    assert _outliers(response) == []
    assert _count_outliers(_DRUG_IGNORES) == 0
