"""Integration tests for the /admin/exam endpoints (admin_exam_service).

Covers the segment-exam configuration: listing, single lookup, upsert rules,
ordering, copying between segments, the global exam catalog and the
most-frequent helper.

demo.segmentoexame has no seed data, so every row asserted here is created by
this module. Segments use the 991x range and exam types the ``zzt`` prefix.
"""

import json

import pytest

from tests.utils.utils_test_admin_exam import (
    create_test_global_exam,
    create_test_segment,
    create_test_segment_exam,
    delete_global_exams,
    delete_segment_exams,
    delete_segment_exams_by_type,
    delete_segments,
    get_segment_exam_row,
    get_segment_exam_types,
)
from utils import status

LIST_URL = "/admin/exam/list"
GET_URL = "/admin/exam/get"
UPSERT_URL = "/admin/exam/upsert"
ORDER_URL = "/admin/exam/order"
COPY_URL = "/admin/exam/copy"
TYPES_URL = "/admin/exam/types"
GLOBAL_URL = "/admin/exam/list-global"
MOST_FREQUENT_URL = "/admin/exam/most-frequent"
MOST_FREQUENT_ADD_URL = "/admin/exam/most-frequent/add"

# Segments reserved for this module. 1 and 2 are seed segments and 9901/9902
# belong to test_admin_protocol.py.
_SEG_ORIGIN = 9911
_SEG_ADULT = 9912  # copy destination, tp_segmento = 1
_SEG_PEDIATRIC = 9913  # copy destination, tp_segmento = 2
_SEG_UNAUTHORIZED = 9914  # no usuario_autorizacao row for the demo user
_SEG_UPSERT = 9915

_ALL_SEGMENTS = (
    _SEG_ORIGIN,
    _SEG_ADULT,
    _SEG_PEDIATRIC,
    _SEG_UNAUTHORIZED,
    _SEG_UPSERT,
)

# Exam types owned by this module
_TYPE_REFERENCED = "zzta"  # points at the global catalog through tpexame_ref
_TYPE_PLAIN = "zztb"  # no reference, copied verbatim
_TYPE_NEW = "zztnew"
_GLOBAL_TYPE = "zztref"

# Values stored on the origin segment, overwritten by the catalog on copy
_ORIGIN_MIN = 50
_ORIGIN_MAX = 60
_ORIGIN_REF = "origin ref"

# Values held by the global catalog entry
_GLOBAL_MIN_ADULT = 1
_GLOBAL_MAX_ADULT = 2
_GLOBAL_REF_ADULT = "adult ref"
_GLOBAL_MIN_PEDIATRIC = 3
_GLOBAL_MAX_PEDIATRIC = 4
_GLOBAL_REF_PEDIATRIC = "pediatric ref"

# The types get_exam_types always reports, regardless of collected results
_CALCULATED_TYPES = ["mdrd", "ckd", "ckd21", "cg", "swrtz2", "swrtz1"]


@pytest.fixture(scope="module", autouse=True)
def seed_exam_config():
    """Create the segments, the global catalog entry and the origin exams."""
    create_test_segment(_SEG_ORIGIN, "ZZTest Segment Origin", tp_segment=1)
    create_test_segment(_SEG_ADULT, "ZZTest Segment Adult", tp_segment=1)
    create_test_segment(_SEG_PEDIATRIC, "ZZTest Segment Pediatric", tp_segment=2)
    create_test_segment(_SEG_UNAUTHORIZED, "ZZTest Segment Unauthorized", tp_segment=1)
    create_test_segment(_SEG_UPSERT, "ZZTest Segment Upsert", tp_segment=1)

    create_test_global_exam(
        _GLOBAL_TYPE,
        "ZZTest Global Exam",
        min_adult=_GLOBAL_MIN_ADULT,
        max_adult=_GLOBAL_MAX_ADULT,
        ref_adult=_GLOBAL_REF_ADULT,
        min_pediatric=_GLOBAL_MIN_PEDIATRIC,
        max_pediatric=_GLOBAL_MAX_PEDIATRIC,
        ref_pediatric=_GLOBAL_REF_PEDIATRIC,
    )

    # ordered by name: "ZZTest Exam A" then "ZZTest Exam B"
    create_test_segment_exam(
        _SEG_ORIGIN,
        _TYPE_REFERENCED,
        name="ZZTest Exam A",
        initials="ZA",
        min=_ORIGIN_MIN,
        max=_ORIGIN_MAX,
        ref=_ORIGIN_REF,
        order=2,
        tp_exam_ref=_GLOBAL_TYPE,
    )
    create_test_segment_exam(
        _SEG_ORIGIN,
        _TYPE_PLAIN,
        name="ZZTest Exam B",
        initials="ZB",
        min=70,
        max=80,
        ref="origin ref b",
        order=1,
    )

    yield

    delete_segment_exams(_ALL_SEGMENTS)
    delete_segment_exams_by_type((_TYPE_REFERENCED, _TYPE_PLAIN, _TYPE_NEW))
    delete_segments(_ALL_SEGMENTS)
    delete_global_exams((_GLOBAL_TYPE,))


@pytest.fixture
def clean_destinations():
    """Empty the copy destinations before and after a copy test."""
    delete_segment_exams((_SEG_ADULT, _SEG_PEDIATRIC))
    yield
    delete_segment_exams((_SEG_ADULT, _SEG_PEDIATRIC))


@pytest.fixture
def clean_upsert_segment():
    """Empty the segment the upsert/order tests write to."""
    delete_segment_exams((_SEG_UPSERT, _SEG_UNAUTHORIZED))
    yield
    delete_segment_exams((_SEG_UPSERT, _SEG_UNAUTHORIZED))


def _post(client, headers, url, payload):
    return client.post(url, data=json.dumps(payload), headers=headers)


def _data(response):
    return response.get_json()["data"]


def _upsert(client, headers, **payload):
    body = {"idSegment": _SEG_UPSERT, "type": _TYPE_NEW}
    body.update(payload)

    return _post(client, headers, UPSERT_URL, body)


# ---------------------------------------------------------------------------
# listing
# ---------------------------------------------------------------------------


def test_list_returns_segment_exams_ordered_by_name(client, admin_headers):
    """List: a segment's exams come back ordered by name with the segment attached"""
    response = _post(client, admin_headers, LIST_URL, {"idSegment": _SEG_ORIGIN})

    assert response.status_code == status.HTTP_200_OK
    exams = _data(response)
    assert [e["type"] for e in exams] == [_TYPE_REFERENCED, _TYPE_PLAIN]

    first = exams[0]
    assert first["idSegment"] == _SEG_ORIGIN
    assert first["segment"] == "ZZTest Segment Origin"
    assert first["name"] == "ZZTest Exam A"
    assert first["initials"] == "ZA"
    assert first["min"] == _ORIGIN_MIN
    assert first["max"] == _ORIGIN_MAX
    assert first["ref"] == _ORIGIN_REF
    assert first["order"] == 2
    assert first["active"] is True
    assert first["tpExamRef"] == _GLOBAL_TYPE


def test_list_of_a_segment_without_exams_is_empty(client, admin_headers):
    """List: a segment with no configured exams returns an empty list"""
    response = _post(client, admin_headers, LIST_URL, {"idSegment": _SEG_UNAUTHORIZED})

    assert response.status_code == status.HTTP_200_OK
    assert _data(response) == []


def test_list_requires_a_read_config_exams_permission(client, viewer_headers):
    """List: a role without READ_CONFIG_EXAMS is rejected"""
    response = _post(client, viewer_headers, LIST_URL, {"idSegment": _SEG_ORIGIN})

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_get_returns_a_single_exam_matching_case_insensitively(client, admin_headers):
    """Get: the requested exam type is matched lowercased"""
    response = _post(
        client,
        admin_headers,
        GET_URL,
        {"idSegment": _SEG_ORIGIN, "examType": _TYPE_REFERENCED.upper()},
    )

    assert response.status_code == status.HTTP_200_OK
    data = _data(response)
    assert data["type"] == _TYPE_REFERENCED
    assert data["segment"] == "ZZTest Segment Origin"
    assert data["tpExamRef"] == _GLOBAL_TYPE


def test_get_unknown_exam_returns_not_found(client, admin_headers):
    """Get: an exam type the segment does not configure returns 404"""
    response = _post(
        client,
        admin_headers,
        GET_URL,
        {"idSegment": _SEG_ORIGIN, "examType": "zzt-unknown"},
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.get_json()["code"] == "errors.notFound"


def test_get_rejects_a_payload_without_the_exam_type(client, admin_headers):
    """Get: a payload missing examType fails pydantic validation"""
    response = _post(client, admin_headers, GET_URL, {"idSegment": _SEG_ORIGIN})

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["message"] == "Parâmetros inválidos"


# ---------------------------------------------------------------------------
# upsert
# ---------------------------------------------------------------------------


def test_upsert_creates_a_segment_exam(client, admin_headers, clean_upsert_segment):
    """Upsert: an exam the segment does not have yet is created"""
    response = _upsert(
        client,
        admin_headers,
        initials="NW",
        name="ZZTest New Exam",
        min=1,
        max=9,
        ref="new ref",
        active=True,
        tpExamRef=_GLOBAL_TYPE,
    )

    assert response.status_code == status.HTTP_200_OK
    assert _data(response)["segment"] == "ZZTest Segment Upsert"

    row = get_segment_exam_row(_SEG_UPSERT, _TYPE_NEW)
    assert row is not None
    assert row.nome == "ZZTest New Exam"
    assert row.abrev == "NW"
    assert row.min == 1
    assert row.max == 9
    assert row.referencia == "new ref"
    assert row.ativo is True
    assert row.tpexame_ref == _GLOBAL_TYPE
    # the insert path never assigns a position — ordering is a separate call
    assert row.posicao is None


def test_upsert_lowercases_the_exam_type(client, admin_headers, clean_upsert_segment):
    """Upsert: the exam type is normalized to lowercase before being stored"""
    response = _upsert(client, admin_headers, type=_TYPE_NEW.upper(), name="ZZTest Upper")

    assert response.status_code == status.HTTP_200_OK
    assert _data(response)["type"] == _TYPE_NEW
    assert get_segment_exam_row(_SEG_UPSERT, _TYPE_NEW) is not None


def test_upsert_updates_an_existing_segment_exam(
    client, admin_headers, clean_upsert_segment
):
    """Upsert: a second call on the same type edits the stored exam"""
    create_test_segment_exam(
        _SEG_UPSERT,
        _TYPE_NEW,
        name="ZZTest Before",
        initials="BF",
        min=1,
        max=2,
        ref="before",
        order=7,
        active=True,
    )

    response = _upsert(
        client,
        admin_headers,
        name="ZZTest After",
        initials="AF",
        min=3,
        max=4,
        ref="after",
        active=False,
    )

    assert response.status_code == status.HTTP_200_OK

    row = get_segment_exam_row(_SEG_UPSERT, _TYPE_NEW)
    assert row.nome == "ZZTest After"
    assert row.abrev == "AF"
    assert row.min == 3
    assert row.max == 4
    assert row.referencia == "after"
    assert row.ativo is False
    # the update path leaves the position untouched
    assert row.posicao == 7


def test_upsert_keeps_omitted_fields_untouched(
    client, admin_headers, clean_upsert_segment
):
    """Upsert: fields absent from the payload keep their stored value"""
    create_test_segment_exam(
        _SEG_UPSERT,
        _TYPE_NEW,
        name="ZZTest Keep",
        initials="KP",
        min=11,
        max=22,
        ref="keep ref",
        active=True,
    )

    response = _upsert(client, admin_headers, name="ZZTest Renamed")

    assert response.status_code == status.HTTP_200_OK

    row = get_segment_exam_row(_SEG_UPSERT, _TYPE_NEW)
    assert row.nome == "ZZTest Renamed"
    assert row.abrev == "KP"
    assert row.min == 11
    assert row.max == 22
    assert row.referencia == "keep ref"
    assert row.ativo is True


def test_upsert_escapes_html_in_text_fields(
    client, admin_headers, clean_upsert_segment
):
    """Upsert: html in the free text fields is escaped before being stored"""
    response = _upsert(
        client, admin_headers, name="<script>alert(1)</script>", initials="<b>"
    )

    assert response.status_code == status.HTTP_200_OK

    row = get_segment_exam_row(_SEG_UPSERT, _TYPE_NEW)
    assert "<script>" not in row.nome
    assert row.nome == "&lt;script&gt;alert(1)&lt;/script&gt;"
    assert row.abrev == "&lt;b&gt;"


@pytest.mark.parametrize(
    "payload", [{"idSegment": None}, {"type": None}], ids=["no-segment", "no-type"]
)
def test_upsert_rejects_missing_parameters(client, admin_headers, payload):
    """Upsert: idSegment and type are both required"""
    response = _upsert(client, admin_headers, **payload)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"


def test_upsert_rejects_a_reference_longer_than_250_chars(
    client, admin_headers, clean_upsert_segment
):
    """Upsert: the reference field is capped at 250 characters"""
    response = _upsert(client, admin_headers, name="ZZTest Long Ref", ref="x" * 251)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"
    assert get_segment_exam_row(_SEG_UPSERT, _TYPE_NEW) is None


def test_upsert_accepts_a_reference_of_exactly_250_chars(
    client, admin_headers, clean_upsert_segment
):
    """Upsert: a 250 character reference is still accepted"""
    response = _upsert(client, admin_headers, name="ZZTest Max Ref", ref="x" * 250)

    assert response.status_code == status.HTTP_200_OK
    assert get_segment_exam_row(_SEG_UPSERT, _TYPE_NEW).referencia == "x" * 250


def test_upsert_rejects_recreating_an_active_exam(
    client, admin_headers, clean_upsert_segment
):
    """Upsert: creating an exam the segment already has active is refused"""
    create_test_segment_exam(
        _SEG_UPSERT, _TYPE_NEW, name="ZZTest Already There", active=True
    )

    response = _upsert(client, admin_headers, new=True, name="ZZTest Duplicate")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.get_json()["code"] == "errors.businessRules"
    assert get_segment_exam_row(_SEG_UPSERT, _TYPE_NEW).nome == "ZZTest Already There"


def test_upsert_reactivates_an_inactive_exam(
    client, admin_headers, clean_upsert_segment
):
    """Upsert: creating over an inactive exam reuses and reactivates the row"""
    create_test_segment_exam(
        _SEG_UPSERT, _TYPE_NEW, name="ZZTest Disabled", active=False
    )

    response = _upsert(
        client, admin_headers, new=True, name="ZZTest Reactivated", active=True
    )

    assert response.status_code == status.HTTP_200_OK

    row = get_segment_exam_row(_SEG_UPSERT, _TYPE_NEW)
    assert row.nome == "ZZTest Reactivated"
    assert row.ativo is True


def test_upsert_rejects_an_unauthorized_segment(client, config_manager_headers):
    """Upsert: a user without authorization on the segment is rejected"""
    response = _post(
        client,
        config_manager_headers,
        UPSERT_URL,
        {
            "idSegment": _SEG_UNAUTHORIZED,
            "type": _TYPE_NEW,
            "name": "ZZTest Forbidden",
        },
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.get_json()["code"] == "errors.businessRules"
    assert get_segment_exam_row(_SEG_UNAUTHORIZED, _TYPE_NEW) is None


def test_upsert_requires_a_write_config_exams_permission(client, analyst_headers):
    """Upsert: a read-only role cannot change the exam configuration"""
    response = _post(
        client,
        analyst_headers,
        UPSERT_URL,
        {"idSegment": _SEG_UPSERT, "type": _TYPE_NEW, "name": "ZZTest Denied"},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert get_segment_exam_row(_SEG_UPSERT, _TYPE_NEW) is None


# ---------------------------------------------------------------------------
# ordering
# ---------------------------------------------------------------------------


def test_set_exams_order_assigns_positions_in_the_given_order(
    client, admin_headers, clean_upsert_segment
):
    """Order: the listed exams get positions following the payload order"""
    create_test_segment_exam(_SEG_UPSERT, "zzt1", name="ZZTest One", order=5)
    create_test_segment_exam(_SEG_UPSERT, "zzt2", name="ZZTest Two", order=5)
    create_test_segment_exam(_SEG_UPSERT, "zzt3", name="ZZTest Three", order=5)

    response = _post(
        client,
        admin_headers,
        ORDER_URL,
        {"idSegment": _SEG_UPSERT, "exams": ["zzt3", "zzt1"]},
    )

    assert response.status_code == status.HTTP_200_OK
    assert get_segment_exam_row(_SEG_UPSERT, "zzt3").posicao == 0
    assert get_segment_exam_row(_SEG_UPSERT, "zzt1").posicao == 1
    # everything left out of the payload is pushed to the end
    assert get_segment_exam_row(_SEG_UPSERT, "zzt2").posicao == 99


def test_set_exams_order_ignores_unknown_exam_types(
    client, admin_headers, clean_upsert_segment
):
    """Order: an exam type the segment does not have is skipped"""
    create_test_segment_exam(_SEG_UPSERT, "zzt1", name="ZZTest One", order=5)

    response = _post(
        client,
        admin_headers,
        ORDER_URL,
        {"idSegment": _SEG_UPSERT, "exams": ["zzt-missing", "zzt1"]},
    )

    assert response.status_code == status.HTTP_200_OK
    assert get_segment_exam_row(_SEG_UPSERT, "zzt1").posicao == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"idSegment": _SEG_UPSERT, "exams": []},
        {"idSegment": None, "exams": ["zzt1"]},
    ],
    ids=["no-exams", "no-segment"],
)
def test_set_exams_order_rejects_missing_parameters(client, admin_headers, payload):
    """Order: both the segment and a non-empty exam list are required"""
    response = _post(client, admin_headers, ORDER_URL, payload)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"


def test_set_exams_order_rejects_an_unauthorized_segment(
    client, config_manager_headers, clean_upsert_segment
):
    """Order: a user without authorization on the segment is rejected"""
    create_test_segment_exam(_SEG_UNAUTHORIZED, "zzt1", name="ZZTest One", order=5)

    response = _post(
        client,
        config_manager_headers,
        ORDER_URL,
        {"idSegment": _SEG_UNAUTHORIZED, "exams": ["zzt1"]},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    # businessRules, not authorizationError: the role holds WRITE_CONFIG_EXAMS
    # and is stopped by the segment authorization check
    assert response.get_json()["code"] == "errors.businessRules"
    assert get_segment_exam_row(_SEG_UNAUTHORIZED, "zzt1").posicao == 5


# ---------------------------------------------------------------------------
# copy between segments
# ---------------------------------------------------------------------------


def test_copy_exams_clones_the_configuration(
    client, admin_headers, clean_destinations
):
    """Copy: every exam of the origin segment lands on the destination"""
    response = _post(
        client,
        admin_headers,
        COPY_URL,
        {"idSegmentOrigin": _SEG_ORIGIN, "idSegmentDestiny": _SEG_ADULT},
    )

    assert response.status_code == status.HTTP_200_OK
    assert _data(response) == 2
    assert sorted(get_segment_exam_types(_SEG_ADULT)) == sorted(
        [_TYPE_REFERENCED, _TYPE_PLAIN]
    )

    # an exam without a catalog reference is copied verbatim
    plain = get_segment_exam_row(_SEG_ADULT, _TYPE_PLAIN)
    assert plain.min == 70
    assert plain.max == 80
    assert plain.referencia == "origin ref b"
    assert plain.nome == "ZZTest Exam B"


def test_copy_exams_applies_the_adult_catalog_range(
    client, admin_headers, clean_destinations
):
    """Copy: a referenced exam takes the adult range of the global catalog"""
    _post(
        client,
        admin_headers,
        COPY_URL,
        {"idSegmentOrigin": _SEG_ORIGIN, "idSegmentDestiny": _SEG_ADULT},
    )

    referenced = get_segment_exam_row(_SEG_ADULT, _TYPE_REFERENCED)
    assert referenced.min == _GLOBAL_MIN_ADULT
    assert referenced.max == _GLOBAL_MAX_ADULT
    assert referenced.referencia == _GLOBAL_REF_ADULT
    # the origin values are replaced, not carried over
    assert referenced.min != _ORIGIN_MIN


def test_copy_exams_applies_the_pediatric_catalog_range(
    client, admin_headers, clean_destinations
):
    """Copy: a non-adult destination takes the pediatric range instead"""
    _post(
        client,
        admin_headers,
        COPY_URL,
        {"idSegmentOrigin": _SEG_ORIGIN, "idSegmentDestiny": _SEG_PEDIATRIC},
    )

    referenced = get_segment_exam_row(_SEG_PEDIATRIC, _TYPE_REFERENCED)
    assert referenced.min == _GLOBAL_MIN_PEDIATRIC
    assert referenced.max == _GLOBAL_MAX_PEDIATRIC
    assert referenced.referencia == _GLOBAL_REF_PEDIATRIC


def test_copy_exams_keeps_exams_the_destination_already_has(
    client, admin_headers, clean_destinations
):
    """Copy: exams already configured on the destination are left untouched"""
    create_test_segment_exam(
        _SEG_ADULT,
        _TYPE_PLAIN,
        name="ZZTest Preexisting",
        min=999,
        max=1000,
        ref="preexisting",
    )

    response = _post(
        client,
        admin_headers,
        COPY_URL,
        {"idSegmentOrigin": _SEG_ORIGIN, "idSegmentDestiny": _SEG_ADULT},
    )

    assert response.status_code == status.HTTP_200_OK
    assert _data(response) == 1

    kept = get_segment_exam_row(_SEG_ADULT, _TYPE_PLAIN)
    assert kept.nome == "ZZTest Preexisting"
    assert kept.min == 999


@pytest.mark.parametrize(
    "payload",
    [
        {"idSegmentOrigin": None, "idSegmentDestiny": _SEG_ADULT},
        {"idSegmentOrigin": _SEG_ORIGIN, "idSegmentDestiny": _SEG_ORIGIN},
    ],
    ids=["no-origin", "same-segment"],
)
def test_copy_exams_rejects_invalid_segment_pairs(client, admin_headers, payload):
    """Copy: the origin is required and must differ from the destination"""
    response = _post(client, admin_headers, COPY_URL, payload)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.unauthorizedUser"


def test_copy_exams_requires_the_copy_permission(client, config_manager_headers):
    """Copy: a role without ADMIN_EXAMS__COPY is rejected"""
    response = _post(
        client,
        config_manager_headers,
        COPY_URL,
        {"idSegmentOrigin": _SEG_ORIGIN, "idSegmentDestiny": _SEG_ADULT},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert get_segment_exam_types(_SEG_ADULT) == []


# ---------------------------------------------------------------------------
# exam types and the global catalog
# ---------------------------------------------------------------------------


def test_exam_types_include_the_calculated_ones_and_recent_results(
    client, admin_headers
):
    """Types: the calculated types come first, followed by recently collected ones"""
    response = client.get(TYPES_URL, headers=admin_headers)

    assert response.status_code == status.HTTP_200_OK
    types = _data(response)
    assert types[: len(_CALCULATED_TYPES)] == _CALCULATED_TYPES
    # the seed data holds one creatinina result collected today
    assert "cr" in types
    # results older than 30 days are not offered
    assert "tgo" not in types
    assert "tgp" not in types
    assert all(t == t.lower() for t in types)


def test_global_exams_expose_both_age_ranges(client, admin_headers):
    """Global: the catalog reports the adult and pediatric ranges of each exam"""
    response = client.get(GLOBAL_URL, headers=admin_headers)

    assert response.status_code == status.HTTP_200_OK
    catalog = {e["tpexam"]: e for e in _data(response)}
    assert _GLOBAL_TYPE in catalog

    entry = catalog[_GLOBAL_TYPE]
    assert entry["name"] == "ZZTest Global Exam"
    assert entry["measureUnit"] == "mg/dL"
    assert entry["min_adult"] == _GLOBAL_MIN_ADULT
    assert entry["max_adult"] == _GLOBAL_MAX_ADULT
    assert entry["ref_adult"] == _GLOBAL_REF_ADULT
    assert entry["min_pediatric"] == _GLOBAL_MIN_PEDIATRIC
    assert entry["max_pediatric"] == _GLOBAL_MAX_PEDIATRIC
    assert entry["ref_pediatric"] == _GLOBAL_REF_PEDIATRIC


def test_global_exams_omit_inactive_entries(client, admin_headers):
    """Global: an inactive catalog entry is not offered"""
    inactive_type = "zztoff"
    create_test_global_exam(inactive_type, "ZZTest Inactive Global", active=False)

    try:
        response = client.get(GLOBAL_URL, headers=admin_headers)

        assert response.status_code == status.HTTP_200_OK
        assert inactive_type not in [e["tpexam"] for e in _data(response)]
    finally:
        delete_global_exams((inactive_type,))


# ---------------------------------------------------------------------------
# most frequent exams
# ---------------------------------------------------------------------------


def test_most_frequent_ranks_collected_exams_by_volume(client, admin_headers):
    """Most frequent: collected exam types are ranked by how many results they have"""
    response = client.get(MOST_FREQUENT_URL, headers=admin_headers)

    assert response.status_code == status.HTTP_200_OK
    exams = _data(response)
    assert exams != []
    assert set(exams[0].keys()) == {"type", "count", "min", "max"}

    counts = [e["count"] for e in exams]
    assert counts == sorted(counts, reverse=True)

    creatinina = next(e for e in exams if e["type"] == "CR")
    assert creatinina["count"] > 0
    assert creatinina["min"] <= creatinina["max"]


def test_most_frequent_requires_its_own_permission(client, config_manager_headers):
    """Most frequent: a role without ADMIN_EXAMS__MOST_FREQUENT is rejected"""
    response = client.get(MOST_FREQUENT_URL, headers=config_manager_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_add_most_frequent_registers_only_the_missing_types(
    client, admin_headers, clean_upsert_segment
):
    """Add most frequent: types the segment already has are not duplicated"""
    create_test_segment_exam(
        _SEG_UPSERT, "zzt1", name="ZZTest Existing", order=3, active=True
    )

    response = _post(
        client,
        admin_headers,
        MOST_FREQUENT_ADD_URL,
        {"idSegment": _SEG_UPSERT, "examTypes": ["ZZT1", "ZZT2"]},
    )

    assert response.status_code == status.HTTP_200_OK
    assert sorted(get_segment_exam_types(_SEG_UPSERT)) == ["zzt1", "zzt2"]

    # the pre-existing exam keeps its configuration
    existing = get_segment_exam_row(_SEG_UPSERT, "zzt1")
    assert existing.nome == "ZZTest Existing"
    assert existing.posicao == 3
    assert existing.ativo is True

    # new entries land disabled and last, waiting to be configured
    added = get_segment_exam_row(_SEG_UPSERT, "zzt2")
    assert added.nome == "ZZT2"
    assert added.ativo is False
    assert added.posicao == 99


def test_add_most_frequent_requires_its_own_permission(
    client, config_manager_headers, clean_upsert_segment
):
    """Add most frequent: a role without ADMIN_EXAMS__MOST_FREQUENT is rejected"""
    response = _post(
        client,
        config_manager_headers,
        MOST_FREQUENT_ADD_URL,
        {"idSegment": _SEG_UPSERT, "examTypes": ["ZZT2"]},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert get_segment_exam_types(_SEG_UPSERT) == []
