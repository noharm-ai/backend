"""Integration tests for the admin copy-drug-attributes endpoint.

``POST /admin/drug/copy-attributes``
(``admin_drug_service.copy_drug_attributes`` /
``admin_drug_repository.copy_attributes``) is the bulk action of the drug
curation screen. It had no coverage at all, and it is the widest write in the
admin area: a single call rewrites the chosen attributes of *every*
``medatributos`` row of a segment, in one of two modes.

* ``fromAdminSchema: true`` (the default) takes the values from the shared
  substance catalog — the tag columns of ``public.substancia`` become the
  boolean flags, and the kidney/liver columns are picked by the destination
  segment's type, so an adult and a pediatric segment get different values
  from the same substance.
* ``fromAdminSchema: false`` copies from another segment of the same schema,
  which additionally allows the two cost attributes.

The rules that protect a curator's work are the point of most tests here:
only the attributes named in the request are written, rows already edited by a
real user are skipped unless ``overwriteAll`` is used (and that flag needs a
permission ``CURATOR`` does not have), drugs with no substance are never
touched, and every affected row gets an audit entry.

Each test seeds its own rows, because a copy leaves the rows it touched marked
as curated, which would change what a later copy is allowed to do. The
destination segments are created by this module (``9911`` block) so a copy
never reaches the seed data of the demo schema, and drug/substance ids use the
reserved ``>= 90000`` range (91000 block).
"""

import pytest
from sqlalchemy import bindparam, text

from models.enums import DrugAttributesAuditTypeEnum
from tests.conftest import session, session_commit
from utils import status

URL = "/admin/drug/copy-attributes"

# Segments created by this module. Every copy is aimed at one of them, so the
# schema-wide statement can only ever reach this module's rows.
_SEG_REFERENCE = 9911  # adult destination, fed from the substance catalog
_SEG_PEDIATRIC = 9912  # pediatric destination, asserts the column choice
_SEG_ORIGIN = 9913  # source of the segment-to-segment copy
_SEG_DESTINY = 9914  # destination of the segment-to-segment copy

_SEGMENTS = (
    (_SEG_REFERENCE, "ZZTest Segmento Referencia", 1),
    (_SEG_PEDIATRIC, "ZZTest Segmento Pediatrico", 2),
    (_SEG_ORIGIN, "ZZTest Segmento Origem", 1),
    (_SEG_DESTINY, "ZZTest Segmento Destino", 1),
)

# Ids reserved for this module (91000 block, distinct from other modules').
_SCTID = 91001

_DRUG_UNCURATED = 91001  # attributes never edited by a user -> always copied
_DRUG_CURATED = 91002  # edited by a real user -> only with overwriteAll
_DRUG_NO_SUBSTANCE = 91003  # no sctid -> outside the copy, whatever the flags
_DRUG_PEDIATRIC = 91004  # lives on the pediatric destination
_DRUG_SEGMENT_COPY = 91005  # lives on both segment-to-segment segments

_DRUG_IDS = (
    _DRUG_UNCURATED,
    _DRUG_CURATED,
    _DRUG_NO_SUBSTANCE,
    _DRUG_PEDIATRIC,
    _DRUG_SEGMENT_COPY,
)

# Substance reference values. The tags drive the boolean attributes; the
# kidney/liver pairs differ so the segment type is observable.
_TAGS = ["antimicro", "tube", "dialyzable"]
_KIDNEY_ADULT = 30
_KIDNEY_PEDIATRIC = 11
_LIVER_ADULT = 40
_LIVER_PEDIATRIC = 12
_PLATELETS = 50
_FALL_RISK = 3
_LACTATING = "2"
_PREGNANT = "4"

# Values seeded on the origin segment of the segment-to-segment copy
_ORIGIN_KIDNEY = 77
_ORIGIN_PRICE = 9.5
_ORIGIN_PRICE_UNIT = "4"

# seed demo.unidademedida rows
_DESTINY_PRICE_UNIT = "1"

# public.usuario seed ids
_ADMIN_ID = 2  # behind admin_headers, holds ADMIN_DRUGS__OVERWRITE_ATTRIBUTES
_CURATOR_ID = 3  # behind curator_headers, holds ADMIN_DRUGS only
_OTHER_USER_ID = 8  # a hospital user, so its rows count as curated

# every boolean attribute the substance catalog can fill
_TAG_ATTRIBUTES = [
    "antimicro",
    "mav",
    "controlados",
    "idoso",
    "linhabranca",
    "sonda",
    "quimio",
    "dialisavel",
    "jejum",
    "naopadronizado",
]


@pytest.fixture(scope="module", autouse=True)
def seed_segments(clean_test_artifacts):  # noqa: ARG001
    """Create the destination/origin segments used by every test.

    Segments fall outside the id windows the shared cleanup wipes, so they are
    removed here — and also before the inserts, so an interrupted run does not
    leave the next one stuck on the primary key.
    """
    _delete_segments()

    for id_segment, name, segment_type in _SEGMENTS:
        session.execute(
            text(
                "INSERT INTO demo.segmento (idsegmento, nome, status, tp_segmento, cpoe) "
                "VALUES (:id, :name, 1, :segment_type, false)"
            ),
            {"id": id_segment, "name": name, "segment_type": segment_type},
        )
    session_commit()

    yield

    _delete_segments()


def _delete_segments():
    """Remove this module's segments."""
    session.execute(
        text("DELETE FROM demo.segmento WHERE idsegmento IN :ids").bindparams(
            bindparam("ids", expanding=True)
        ),
        {"ids": [segment[0] for segment in _SEGMENTS]},
    )
    session_commit()


@pytest.fixture(autouse=True)
def seed_drugs():
    """Substance, drugs and attribute rows, rebuilt for every test.

    A successful copy stamps ``update_by`` on the rows it touched, which turns
    them into curated rows; rebuilding keeps each test independent of the ones
    that ran before it.
    """
    _delete_drugs()

    session.execute(
        text(
            "INSERT INTO public.substancia "
            "(sctid, nome, link, ativo, unidadepadrao, tags, "
            "renal_adulto, renal_pediatrico, hepatico_adulto, hepatico_pediatrico, "
            "plaquetas, risco_queda, lactante, gestante) "
            "VALUES (:id, 'ZZTest Substancia Copia', '', true, 'mg', :tags, "
            ":kidney_adult, :kidney_pediatric, :liver_adult, :liver_pediatric, "
            ":platelets, :fall_risk, :lactating, :pregnant)"
        ),
        {
            "id": _SCTID,
            "tags": _TAGS,
            "kidney_adult": _KIDNEY_ADULT,
            "kidney_pediatric": _KIDNEY_PEDIATRIC,
            "liver_adult": _LIVER_ADULT,
            "liver_pediatric": _LIVER_PEDIATRIC,
            "platelets": _PLATELETS,
            "fall_risk": _FALL_RISK,
            "lactating": _LACTATING,
            "pregnant": _PREGNANT,
        },
    )

    for id_drug, name, sctid in (
        (_DRUG_UNCURATED, "ZZTest Medicamento Nao Curado", _SCTID),
        (_DRUG_CURATED, "ZZTest Medicamento Curado", _SCTID),
        (_DRUG_NO_SUBSTANCE, "ZZTest Medicamento Sem Substancia Copia", None),
        (_DRUG_PEDIATRIC, "ZZTest Medicamento Pediatrico", _SCTID),
        (_DRUG_SEGMENT_COPY, "ZZTest Medicamento Copia Segmento", _SCTID),
    ):
        session.execute(
            text(
                "INSERT INTO demo.medicamento (fkhospital, fkmedicamento, nome, sctid) "
                "VALUES (1, :id, :name, :sctid)"
            ),
            {"id": id_drug, "name": name, "sctid": sctid},
        )

    # blank rows on the reference destination: two of them are copy targets and
    # one is protected by its update_by
    for id_drug, id_segment, update_by in (
        (_DRUG_UNCURATED, _SEG_REFERENCE, None),
        (_DRUG_CURATED, _SEG_REFERENCE, _OTHER_USER_ID),
        (_DRUG_NO_SUBSTANCE, _SEG_REFERENCE, None),
        (_DRUG_PEDIATRIC, _SEG_PEDIATRIC, None),
        (_DRUG_SEGMENT_COPY, _SEG_DESTINY, None),
    ):
        session.execute(
            text(
                "INSERT INTO demo.medatributos "
                "(fkmedicamento, idsegmento, renal, hepatico, plaquetas, "
                "risco_queda, lactante, gestante, antimicro, mav, controlados, "
                "idoso, linhabranca, sonda, quimio, dialisavel, jejum, "
                "naopadronizado, custo, fkunidademedidacusto, update_by) "
                "VALUES (:id_drug, :id_segment, null, null, null, "
                "null, null, null, false, false, false, "
                "false, false, false, false, false, false, "
                "false, 1, :price_unit, :update_by) "
            ),
            {
                "id_drug": id_drug,
                "id_segment": id_segment,
                "price_unit": _DESTINY_PRICE_UNIT,
                "update_by": update_by,
            },
        )

    # the row the segment-to-segment copy reads from
    session.execute(
        text(
            "INSERT INTO demo.medatributos "
            "(fkmedicamento, idsegmento, renal, antimicro, custo, "
            "fkunidademedidacusto, update_by) "
            "VALUES (:id_drug, :id_segment, :kidney, true, :price, :price_unit, "
            ":update_by)"
        ),
        {
            "id_drug": _DRUG_SEGMENT_COPY,
            "id_segment": _SEG_ORIGIN,
            "kidney": _ORIGIN_KIDNEY,
            "price": _ORIGIN_PRICE,
            "price_unit": _ORIGIN_PRICE_UNIT,
            "update_by": _OTHER_USER_ID,
        },
    )
    session_commit()

    yield

    _delete_drugs()


def _delete_drugs():
    """Remove this module's drug rows, attributes and audit trail."""
    for table in ("medatributos_audit", "medatributos", "medicamento"):
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


def _post(client, headers, **body):
    """Call the copy endpoint with the given payload."""
    return client.post(URL, json=body, headers=headers)


def _copy_from_reference(client, headers, attributes, **body):
    """Copy the given attributes from the substance catalog into a segment."""
    payload = {
        "idSegmentDestiny": _SEG_REFERENCE,
        "attributes": attributes,
        "fromAdminSchema": True,
    }
    payload.update(body)

    return _post(client, headers, **payload)


def _attributes(id_drug, id_segment):
    """The attribute row of a drug/segment pair, as a dict."""
    row = session.execute(
        text(
            "SELECT renal, hepatico, plaquetas, risco_queda, lactante, gestante, "
            "antimicro, mav, controlados, idoso, linhabranca, sonda, quimio, "
            "dialisavel, jejum, naopadronizado, custo, fkunidademedidacusto, "
            "update_by "
            "FROM demo.medatributos "
            "WHERE fkmedicamento = :id_drug AND idsegmento = :id_segment"
        ),
        {"id_drug": id_drug, "id_segment": id_segment},
    ).fetchone()

    return dict(row._mapping)


def _audit_rows(id_drug):
    """Copy-from-reference audit entries of a drug."""
    return session.execute(
        text(
            "SELECT idsegmento, extra, created_by FROM demo.medatributos_audit "
            "WHERE fkmedicamento = :id_drug AND tp_audit = :audit_type"
        ),
        {
            "id_drug": id_drug,
            "audit_type": DrugAttributesAuditTypeEnum.COPY_FROM_REFERENCE.value,
        },
    ).fetchall()


def test_copy_attributes_permission_denied(client, analyst_headers):
    """Teste post /admin/drug/copy-attributes - Deve negar acesso sem ADMIN_DRUGS [401]"""
    response = _copy_from_reference(client, analyst_headers, ["antimicro"])

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert _attributes(_DRUG_UNCURATED, _SEG_REFERENCE)["antimicro"] is False


def test_copy_attributes_overwrite_all_requires_extra_permission(
    client, curator_headers
):
    """Teste post /admin/drug/copy-attributes - overwriteAll exige permissão adicional [401]"""
    response = _copy_from_reference(
        client, curator_headers, ["antimicro"], overwriteAll=True
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.get_json()["code"] == "errors.unauthorizedUser"
    assert _attributes(_DRUG_UNCURATED, _SEG_REFERENCE)["antimicro"] is False


def test_copy_attributes_curator_may_copy_without_overwrite(client, curator_headers):
    """Teste post /admin/drug/copy-attributes - CURATOR pode copiar sem overwriteAll"""
    response = _copy_from_reference(client, curator_headers, ["antimicro"])

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == 1
    assert _attributes(_DRUG_UNCURATED, _SEG_REFERENCE)["update_by"] == _CURATOR_ID


def test_copy_attributes_requires_destiny_segment(client, admin_headers):
    """Teste post /admin/drug/copy-attributes - Segmento destino é obrigatório [400]"""
    response = _post(
        client, admin_headers, attributes=["antimicro"], fromAdminSchema=True
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"


def test_copy_attributes_from_segment_requires_origin_segment(client, admin_headers):
    """Teste post /admin/drug/copy-attributes - Cópia entre segmentos exige origem [400]"""
    response = _post(
        client,
        admin_headers,
        idSegmentDestiny=_SEG_DESTINY,
        attributes=["renal"],
        fromAdminSchema=False,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"


def test_copy_attributes_from_segment_rejects_same_segment(client, admin_headers):
    """Teste post /admin/drug/copy-attributes - Origem igual ao destino é recusada [400]"""
    response = _post(
        client,
        admin_headers,
        idSegmentOrigin=_SEG_DESTINY,
        idSegmentDestiny=_SEG_DESTINY,
        attributes=["renal"],
        fromAdminSchema=False,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidParams"


def test_copy_attributes_writes_only_the_requested_attributes(client, admin_headers):
    """Teste post /admin/drug/copy-attributes - Apenas os atributos informados são gravados"""
    response = _copy_from_reference(client, admin_headers, ["antimicro", "renal"])

    assert response.status_code == status.HTTP_200_OK

    attributes = _attributes(_DRUG_UNCURATED, _SEG_REFERENCE)
    assert attributes["antimicro"] is True
    assert attributes["renal"] == _KIDNEY_ADULT
    # the substance also defines these, but they were not requested
    assert attributes["sonda"] is False
    assert attributes["dialisavel"] is False
    assert attributes["hepatico"] is None
    assert attributes["plaquetas"] is None
    assert attributes["update_by"] == _ADMIN_ID


def test_copy_attributes_maps_substance_tags_to_flags(client, admin_headers):
    """Teste post /admin/drug/copy-attributes - Tags da substância viram atributos booleanos"""
    response = _copy_from_reference(client, admin_headers, _TAG_ATTRIBUTES)

    assert response.status_code == status.HTTP_200_OK

    attributes = _attributes(_DRUG_UNCURATED, _SEG_REFERENCE)
    # tags present on the substance
    assert attributes["antimicro"] is True
    assert attributes["sonda"] is True
    assert attributes["dialisavel"] is True
    # every other flag is absent from the tags, so it must be false
    assert attributes["mav"] is False
    assert attributes["controlados"] is False
    assert attributes["idoso"] is False
    assert attributes["linhabranca"] is False
    assert attributes["quimio"] is False
    assert attributes["jejum"] is False
    assert attributes["naopadronizado"] is False


def test_copy_attributes_copies_non_tag_reference_columns(client, admin_headers):
    """Teste post /admin/drug/copy-attributes - Colunas diretas da substância são copiadas"""
    response = _copy_from_reference(
        client,
        admin_headers,
        ["hepatico", "plaquetas", "risco_queda", "lactante", "gestante"],
    )

    assert response.status_code == status.HTTP_200_OK

    attributes = _attributes(_DRUG_UNCURATED, _SEG_REFERENCE)
    assert attributes["hepatico"] == _LIVER_ADULT
    assert attributes["plaquetas"] == _PLATELETS
    assert attributes["risco_queda"] == _FALL_RISK
    assert attributes["lactante"] == _LACTATING
    assert attributes["gestante"] == _PREGNANT


def test_copy_attributes_skips_rows_curated_by_a_user(client, admin_headers):
    """Teste post /admin/drug/copy-attributes - Linhas editadas por usuário são preservadas"""
    response = _copy_from_reference(client, admin_headers, ["antimicro"])

    assert response.status_code == status.HTTP_200_OK
    # only the uncurated row is counted
    assert response.get_json()["data"] == 1

    curated = _attributes(_DRUG_CURATED, _SEG_REFERENCE)
    assert curated["antimicro"] is False
    assert curated["update_by"] == _OTHER_USER_ID


def test_copy_attributes_overwrite_all_includes_curated_rows(client, admin_headers):
    """Teste post /admin/drug/copy-attributes - overwriteAll também grava linhas curadas"""
    response = _copy_from_reference(
        client, admin_headers, ["antimicro"], overwriteAll=True
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == 2

    for id_drug in (_DRUG_UNCURATED, _DRUG_CURATED):
        attributes = _attributes(id_drug, _SEG_REFERENCE)
        assert attributes["antimicro"] is True
        assert attributes["update_by"] == _ADMIN_ID


def test_copy_attributes_ignores_drugs_without_substance(client, admin_headers):
    """Teste post /admin/drug/copy-attributes - Medicamento sem substância não é alterado"""
    response = _copy_from_reference(
        client, admin_headers, ["antimicro"], overwriteAll=True
    )

    assert response.status_code == status.HTTP_200_OK

    # there is no reference to copy from, so the row must stay untouched even
    # though it sits on the destination segment and has no update_by
    untouched = _attributes(_DRUG_NO_SUBSTANCE, _SEG_REFERENCE)
    assert untouched["antimicro"] is False
    assert untouched["update_by"] is None
    assert _audit_rows(_DRUG_NO_SUBSTANCE) == []


def test_copy_attributes_uses_pediatric_reference_for_pediatric_segment(
    client, admin_headers
):
    """Teste post /admin/drug/copy-attributes - Segmento pediátrico usa as colunas pediátricas"""
    response = _copy_from_reference(
        client,
        admin_headers,
        ["renal", "hepatico"],
        idSegmentDestiny=_SEG_PEDIATRIC,
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == 1

    attributes = _attributes(_DRUG_PEDIATRIC, _SEG_PEDIATRIC)
    assert attributes["renal"] == _KIDNEY_PEDIATRIC
    assert attributes["hepatico"] == _LIVER_PEDIATRIC


def test_copy_attributes_from_reference_ignores_cost_attributes(client, admin_headers):
    """Teste post /admin/drug/copy-attributes - Custo não é copiado da substância"""
    response = _copy_from_reference(
        client, admin_headers, ["custo", "fkunidademedidacusto"]
    )

    assert response.status_code == status.HTTP_200_OK

    attributes = _attributes(_DRUG_UNCURATED, _SEG_REFERENCE)
    # the substance catalog holds no cost, so these two are only assignable in
    # the segment-to-segment mode; the row is still stamped as visited
    assert attributes["custo"] == 1
    assert attributes["fkunidademedidacusto"] == _DESTINY_PRICE_UNIT
    assert attributes["update_by"] == _ADMIN_ID


def test_copy_attributes_from_segment_copies_origin_values(client, admin_headers):
    """Teste post /admin/drug/copy-attributes - Cópia entre segmentos usa os valores da origem"""
    response = _post(
        client,
        admin_headers,
        idSegmentOrigin=_SEG_ORIGIN,
        idSegmentDestiny=_SEG_DESTINY,
        attributes=["renal", "antimicro"],
        fromAdminSchema=False,
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == 1

    attributes = _attributes(_DRUG_SEGMENT_COPY, _SEG_DESTINY)
    assert attributes["renal"] == _ORIGIN_KIDNEY
    assert attributes["antimicro"] is True
    # the origin row is the reference, never a target
    assert _attributes(_DRUG_SEGMENT_COPY, _SEG_ORIGIN)["update_by"] == _OTHER_USER_ID


def test_copy_attributes_from_segment_allows_cost_attributes(client, admin_headers):
    """Teste post /admin/drug/copy-attributes - Cópia entre segmentos permite custo"""
    response = _post(
        client,
        admin_headers,
        idSegmentOrigin=_SEG_ORIGIN,
        idSegmentDestiny=_SEG_DESTINY,
        attributes=["custo", "fkunidademedidacusto"],
        fromAdminSchema=False,
    )

    assert response.status_code == status.HTTP_200_OK

    attributes = _attributes(_DRUG_SEGMENT_COPY, _SEG_DESTINY)
    assert attributes["custo"] == pytest.approx(_ORIGIN_PRICE)
    assert attributes["fkunidademedidacusto"] == _ORIGIN_PRICE_UNIT


def test_copy_attributes_records_an_audit_entry_per_affected_row(client, admin_headers):
    """Teste post /admin/drug/copy-attributes - Deve registrar auditoria dos atributos copiados"""
    response = _copy_from_reference(client, admin_headers, ["antimicro", "sonda"])

    assert response.status_code == status.HTTP_200_OK

    audit = _audit_rows(_DRUG_UNCURATED)
    assert len(audit) == 1
    assert audit[0][0] == _SEG_REFERENCE
    assert audit[0][1] == {"attributes": "antimicro,sonda"}
    assert audit[0][2] == _ADMIN_ID
    # the skipped row is not audited either
    assert _audit_rows(_DRUG_CURATED) == []
