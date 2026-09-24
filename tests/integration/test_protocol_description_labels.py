"""Integration tests for the label resolution behind ``GET
/protocol/<id>/description`` (``protocol_service._build_variable_labels``).

A protocol's trigger is written against *variables*, and most variables point
at rows by id: a substance id, a class id, a drug id, an ICD code, a
department, a segment, a route, an exam type. The prescription view renders
that rule in plain language for end users, so the endpoint also ships a
``labels`` map — ``labels[kind][str(id)] -> description`` — with the name
behind every id the variables reference.

``tests/integration/test_protocol.py`` already covers the endpoint itself (the
trigger, the variable list, permissions, unknown ids) and the ``substance`` and
``segment`` label groups. This module covers the rest of the resolution, which
is where the per-kind behaviour differs:

* each remaining group (``class``, ``drug``, ``icd``, ``department``,
  ``route``, ``exam``, ``examRef``) and the exact description format it
  produces — the class and ICD groups prefix the parent class / the code,
  the others are plain names;
* the id collection rules shared by every group: a scalar value instead of a
  list, blank and null values, ids that match nothing, and non-numeric ids on
  a numeric column (which must not reach the database as an integer);
* the ``combination`` variable, which carries its substance/class/drug ids
  under their own keys rather than under ``value``, and whose routes are free
  text and deliberately left unresolved;
* the ``exam`` / ``exam_ref`` variables, which are keyed by a text exam type
  rather than by a numeric id and resolve against different catalogs
  (the schema's active exams vs. the global exam table).
"""

import json

import pytest
from sqlalchemy import text

from tests.conftest import session, session_commit

# Every row this module creates uses a reserved range or a "zzt"/"ZZTest"
# prefix so it never collides with seed data or with the ranges other test
# modules own (test_protocol.py uses protocol ids 9900xx and segment 990011).
_PROTOCOL_ID = 990101

_SUBSTANCE = (9900001001, "ZZTest Substância")
_PARENT_CLASS = ("zztC1", "ZZTest Classe Mãe")
_CHILD_CLASS = ("zztC2", "ZZTest Classe Filha")
_ORPHAN_CLASS = ("zztC3", "ZZTest Classe Sem Mãe")
_DRUG = (9900002, "ZZTest Medicamento")
_ICD = (9900003, "Z998", "ZZTest Diagnóstico")
_DEPARTMENT = (9900004, "ZZTest Setor")
# demo.segmentoexame.idsegmento is a smallint, so the segment id stays small
_SEGMENT = (9931, "ZZTest Segmento Descrição")
_EXAM_TYPE = ("zztexam", "ZZTest Exame do Segmento")
_GLOBAL_EXAM = ("zztgexam", "ZZTest Exame Global")
_ROUTE = ("77", "ZZTest Via")
# demo.hospital.fkhospital is a smallint; only hospital 1 is seeded
_OTHER_HOSPITAL = 999

# ids that exist in no table: the client falls back to rendering the id itself
_MISSING_DRUG_ID = 9900999
_MISSING_ICD = "Z997"

_MAP_ROUTES = [
    {"id": int(_ROUTE[0]), "value": _ROUTE[1]},
    {"id": 78, "value": "ZZTest Via Não Referenciada"},
]


def _insert_protocol(config: dict) -> None:
    """Create the described protocol with the given config."""
    session.execute(
        text(
            "INSERT INTO public.protocolo "
            "(idprotocolo, schema_name, nome, tp_protocolo, tp_situacao, "
            "configuracao, created_at, created_by) "
            "VALUES (:id, 'demo', 'ZZTest Descrição Labels', 1, 1, "
            "CAST(:config AS json), now(), 1)"
        ),
        {"id": _PROTOCOL_ID, "config": json.dumps(config)},
    )
    session_commit()


def _delete_protocol() -> None:
    session.execute(
        text("DELETE FROM public.protocolo WHERE idprotocolo = :id"),
        {"id": _PROTOCOL_ID},
    )
    session_commit()


def _reset_session() -> None:
    """Roll back a failed statement and restore the schema mapping.

    ``tests/conftest.py`` hands out one session for the whole run, so a
    statement that errors while a fixture is setting up would otherwise leave
    the transaction aborted and fail every later test — here and in unrelated
    modules — with "current transaction is aborted".
    """
    session.rollback()
    session.connection(execution_options={"schema_translate_map": {None: "demo"}})


def _clear_owned_rows() -> None:
    """Remove every row this module creates, in dependency order."""
    session.execute(
        text("DELETE FROM public.protocolo WHERE idprotocolo = :id"),
        {"id": _PROTOCOL_ID},
    )
    session.execute(text("DELETE FROM demo.memoria WHERE tipo = 'map-routes'"))
    session.execute(
        text("DELETE FROM public.exame WHERE tpexame = :t"), {"t": _GLOBAL_EXAM[0]}
    )
    session.execute(
        text("DELETE FROM demo.segmentoexame WHERE tpexame = :t"),
        {"t": _EXAM_TYPE[0]},
    )
    session.execute(
        text("DELETE FROM demo.segmento WHERE idsegmento = :id"), {"id": _SEGMENT[0]}
    )
    session.execute(
        text("DELETE FROM demo.setor WHERE fksetor = :id"), {"id": _DEPARTMENT[0]}
    )
    session.execute(
        text("DELETE FROM demo.hospital WHERE fkhospital = :id"),
        {"id": _OTHER_HOSPITAL},
    )
    session.execute(
        text("DELETE FROM public.tb_cid10 WHERE co_cid10 = :id"), {"id": _ICD[0]}
    )
    session.execute(
        text("DELETE FROM demo.medicamento WHERE fkmedicamento = :id"),
        {"id": _DRUG[0]},
    )
    session.execute(text("DELETE FROM public.classe WHERE idclasse LIKE 'zztC%'"))
    session.execute(
        text("DELETE FROM public.substancia WHERE sctid = :id"), {"id": _SUBSTANCE[0]}
    )
    session_commit()


@pytest.fixture
def seed_label_rows():
    """Insert one row per label group, then remove them all.

    The rows are shared by every test in this module; each test creates only
    the protocol whose variables reference them. None of these tables are part
    of the session-wide cleanup, so a run that died before its teardown must
    not leave duplicate keys behind.
    """
    # setup and teardown are inside try/finally so that a statement failing
    # here still rolls the session back and still cleans up: none of these
    # tables are part of the session-wide cleanup in tests/conftest.py
    try:
        _clear_owned_rows()

        session.execute(
            text(
                "INSERT INTO public.substancia (sctid, nome, link, ativo) "
                "VALUES (:id, :name, '', true)"
            ),
            {"id": _SUBSTANCE[0], "name": _SUBSTANCE[1]},
        )
        # a class with a parent renders as "parent - child"; one without renders bare
        for id_class, name, id_parent in (
            (_PARENT_CLASS[0], _PARENT_CLASS[1], None),
            (_CHILD_CLASS[0], _CHILD_CLASS[1], _PARENT_CLASS[0]),
            (_ORPHAN_CLASS[0], _ORPHAN_CLASS[1], None),
        ):
            session.execute(
                text(
                    "INSERT INTO public.classe (idclasse, idclassemae, nome) "
                    "VALUES (:id, :id_parent, :name)"
                ),
                {"id": id_class, "id_parent": id_parent, "name": name},
            )
        session.execute(
            text(
                "INSERT INTO demo.medicamento "
                "(fkmedicamento, fkhospital, nome, created_at) "
                "VALUES (:id, 1, :name, now())"
            ),
            {"id": _DRUG[0], "name": _DRUG[1]},
        )
        session.execute(
            text(
                "INSERT INTO public.tb_cid10 "
                "(co_cid10, nu_cid10, tp_agravo, no_cid10, no_cid10_filtro, st_ativo) "
                "VALUES (:id_int, :id_str, 0, :name, :name, 1)"
            ),
            {"id_int": _ICD[0], "id_str": _ICD[1], "name": _ICD[2]},
        )
        session.execute(
            text(
                "INSERT INTO demo.setor (fksetor, fkhospital, nome) "
                "VALUES (:id, 1, :name)"
            ),
            {"id": _DEPARTMENT[0], "name": _DEPARTMENT[1]},
        )
        session.execute(
            text(
                "INSERT INTO demo.segmento "
                "(idsegmento, nome, status, cpoe, cpoe_ambulatorio) "
                "VALUES (:id, :name, 1, false, false)"
            ),
            {"id": _SEGMENT[0], "name": _SEGMENT[1]},
        )
        session.execute(
            text(
                "INSERT INTO demo.segmentoexame "
                "(idsegmento, tpexame, abrev, nome, min, max, referencia, posicao, "
                "ativo, update_at, update_by) "
                "VALUES (:id_segment, :type_exam, 'ZZ', :name, 1, 10, 'ref', 1, true, "
                "now(), 1)"
            ),
            {
                "id_segment": _SEGMENT[0],
                "type_exam": _EXAM_TYPE[0],
                "name": _EXAM_TYPE[1],
            },
        )
        session.execute(
            text(
                "INSERT INTO public.exame "
                "(tpexame, nome, abrev, unidade, ativo, min_adulto, max_adulto, "
                "referencia_adulto, created_at, created_by) "
                "VALUES (:type_exam, :name, 'ZZG', 'mg', true, 1, 10, 'ref', now(), 1)"
            ),
            {"type_exam": _GLOBAL_EXAM[0], "name": _GLOBAL_EXAM[1]},
        )
        session.execute(
            text(
                "INSERT INTO demo.memoria (tipo, valor, update_at, update_by) "
                "VALUES ('map-routes', CAST(:value AS json), now(), 1)"
            ),
            {"value": json.dumps(_MAP_ROUTES)},
        )
        session_commit()

        yield
    finally:
        _reset_session()
        _clear_owned_rows()


@pytest.fixture
def describe(client, analyst_headers):
    """Create a protocol with the given variables and describe it.

    Returns a callable so each test declares only the variables it cares
    about; the protocol row is removed afterwards either way.
    """
    created = []

    def _describe(variables: list[dict]):
        _insert_protocol({"trigger": "{{v}}", "variables": variables})
        created.append(True)
        response = client.get(
            f"/protocol/{_PROTOCOL_ID}/description", headers=analyst_headers
        )
        assert response.status_code == 200
        return response.get_json()["data"]["labels"]

    yield _describe

    if created:
        _delete_protocol()


# --- one group per variable field ---------------------------------------------


def test_class_label_is_prefixed_by_the_parent_class(seed_label_rows, describe):
    """A class with a parent reads as "parent - child"."""
    labels = describe(
        [{"name": "v", "field": "class", "operator": "IN", "value": [_CHILD_CLASS[0]]}]
    )

    assert labels["class"][_CHILD_CLASS[0]] == f"{_PARENT_CLASS[1]} - {_CHILD_CLASS[1]}"


def test_class_label_without_a_parent_is_the_bare_name(seed_label_rows, describe):
    """A top-level class has no prefix to add, so it reads as its own name."""
    labels = describe(
        [{"name": "v", "field": "class", "operator": "IN", "value": [_ORPHAN_CLASS[0]]}]
    )

    assert labels["class"][_ORPHAN_CLASS[0]] == _ORPHAN_CLASS[1]


def test_drug_label_is_the_drug_name(seed_label_rows, describe):
    """An idDrug variable resolves against the caller's schema drug table."""
    labels = describe(
        [{"name": "v", "field": "idDrug", "operator": "IN", "value": [_DRUG[0]]}]
    )

    assert labels["drug"][str(_DRUG[0])] == _DRUG[1]


def test_icd_label_keeps_the_code_in_front_of_the_name(seed_label_rows, describe):
    """ICD codes stay visible: users read the rule as "Z998 - <name>"."""
    labels = describe(
        [{"name": "v", "field": "idIcd", "operator": "IN", "value": [_ICD[1]]}]
    )

    assert labels["icd"][_ICD[1]] == f"{_ICD[1]} - {_ICD[2]}"


def test_department_label_is_the_department_name(seed_label_rows, describe):
    """An idDepartment variable resolves against demo.setor."""
    labels = describe(
        [
            {
                "name": "v",
                "field": "idDepartment",
                "operator": "IN",
                "value": [_DEPARTMENT[0]],
            }
        ]
    )

    assert labels["department"][str(_DEPARTMENT[0])] == _DEPARTMENT[1]


def test_department_label_dedupes_the_same_id_across_hospitals(
    seed_label_rows, describe
):
    """The same fksetor may exist once per hospital; one label comes back."""
    session.execute(
        text(
            "INSERT INTO demo.hospital (fkhospital, nome) VALUES (:id, :name) "
            "ON CONFLICT (fkhospital) DO NOTHING"
        ),
        {"id": _OTHER_HOSPITAL, "name": "ZZTest Hospital"},
    )
    session.execute(
        text(
            "INSERT INTO demo.setor (fksetor, fkhospital, nome) "
            "VALUES (:id, :id_hospital, :name)"
        ),
        {
            "id": _DEPARTMENT[0],
            "id_hospital": _OTHER_HOSPITAL,
            "name": "ZZTest Setor Outro Hospital",
        },
    )
    session_commit()

    try:
        labels = describe(
            [
                {
                    "name": "v",
                    "field": "idDepartment",
                    "operator": "IN",
                    "value": [_DEPARTMENT[0]],
                }
            ]
        )

        # one entry, not one per hospital
        assert list(labels["department"].keys()) == [str(_DEPARTMENT[0])]
        # min(nome) breaks the tie deterministically
        assert labels["department"][str(_DEPARTMENT[0])] == _DEPARTMENT[1]
    finally:
        session.execute(
            text("DELETE FROM demo.setor WHERE fkhospital = :id"),
            {"id": _OTHER_HOSPITAL},
        )
        session_commit()


def test_route_label_comes_from_the_map_routes_memory(seed_label_rows, describe):
    """Routes are configured per schema in the map-routes memory, not in a table."""
    labels = describe(
        [{"name": "v", "field": "route", "operator": "IN", "value": [_ROUTE[0]]}]
    )

    assert labels["route"] == {_ROUTE[0]: _ROUTE[1]}


def test_route_label_ignores_unreferenced_routes(seed_label_rows, describe):
    """Only the routes the variables mention are returned, not the whole map."""
    labels = describe(
        [{"name": "v", "field": "route", "operator": "IN", "value": [_ROUTE[0]]}]
    )

    assert "78" not in labels["route"]


def test_route_group_is_empty_when_no_route_matches(seed_label_rows, describe):
    """An unknown route still produces the group, empty, and never raises."""
    labels = describe(
        [{"name": "v", "field": "route", "operator": "IN", "value": ["99999"]}]
    )

    assert labels["route"] == {}


def test_exam_label_comes_from_the_schema_exams(seed_label_rows, describe):
    """An exam variable is keyed by exam type and reads the schema catalog."""
    labels = describe(
        [
            {
                "name": "v",
                "field": "exam",
                "operator": ">",
                "examType": _EXAM_TYPE[0],
                "value": 10,
            }
        ]
    )

    assert labels["exam"] == {_EXAM_TYPE[0]: _EXAM_TYPE[1]}


def test_exam_ref_label_comes_from_the_global_exam_table(seed_label_rows, describe):
    """An exam_ref variable resolves against the global exam catalog instead."""
    labels = describe(
        [
            {
                "name": "v",
                "field": "exam_ref",
                "operator": ">",
                "examRefType": _GLOBAL_EXAM[0],
                "value": 10,
            }
        ]
    )

    assert labels["examRef"] == {_GLOBAL_EXAM[0]: _GLOBAL_EXAM[1]}


# --- the combination variable --------------------------------------------------


def test_combination_resolves_substance_class_and_drug(seed_label_rows, describe):
    """A combination carries its ids under their own keys, not under value."""
    labels = describe(
        [
            {
                "name": "v",
                "field": "combination",
                "operator": "IN",
                "substance": [str(_SUBSTANCE[0])],
                "class": [_CHILD_CLASS[0]],
                "drug": [_DRUG[0]],
            }
        ]
    )

    assert labels["substance"][str(_SUBSTANCE[0])] == _SUBSTANCE[1]
    assert labels["class"][_CHILD_CLASS[0]] == f"{_PARENT_CLASS[1]} - {_CHILD_CLASS[1]}"
    assert labels["drug"][str(_DRUG[0])] == _DRUG[1]


def test_combination_routes_are_left_unresolved(seed_label_rows, describe):
    """Combination routes are free text typed by the user: already readable."""
    labels = describe(
        [
            {
                "name": "v",
                "field": "combination",
                "operator": "IN",
                "substance": [str(_SUBSTANCE[0])],
                "route": ["EV"],
            }
        ]
    )

    assert "route" not in labels


def test_combination_ignores_its_value_field(seed_label_rows, describe):
    """``value`` is not a combination key, so it contributes no labels."""
    labels = describe(
        [
            {
                "name": "v",
                "field": "combination",
                "operator": "IN",
                "value": [_DRUG[0]],
            }
        ]
    )

    assert labels == {}


# --- id collection rules shared by every group --------------------------------


def test_a_scalar_value_is_resolved_like_a_single_item_list(seed_label_rows, describe):
    """Operators such as "=" store a bare value instead of a list."""
    labels = describe(
        [{"name": "v", "field": "idDrug", "operator": "=", "value": _DRUG[0]}]
    )

    assert labels["drug"][str(_DRUG[0])] == _DRUG[1]


def test_an_id_that_matches_nothing_is_left_out(seed_label_rows, describe):
    """Unresolved ids are absent and the client falls back to showing the id."""
    labels = describe(
        [
            {
                "name": "v",
                "field": "idDrug",
                "operator": "IN",
                "value": [_DRUG[0], _MISSING_DRUG_ID],
            }
        ]
    )

    assert str(_MISSING_DRUG_ID) not in labels["drug"]
    assert labels["drug"][str(_DRUG[0])] == _DRUG[1]


def test_an_unmatched_icd_is_left_out(seed_label_rows, describe):
    """The same fallback applies to the code-keyed ICD group."""
    labels = describe(
        [
            {
                "name": "v",
                "field": "idIcd",
                "operator": "IN",
                "value": [_ICD[1], _MISSING_ICD],
            }
        ]
    )

    assert _MISSING_ICD not in labels["icd"]


def test_a_non_numeric_id_never_reaches_a_numeric_column(seed_label_rows, describe):
    """Only digit-like ids are compared against integer columns.

    A malformed config must degrade to "no label", not to a database error.
    """
    labels = describe(
        [
            {
                "name": "v",
                "field": "idDrug",
                "operator": "IN",
                "value": ["not-a-number", _DRUG[0]],
            }
        ]
    )

    assert labels["drug"] == {str(_DRUG[0]): _DRUG[1]}


def test_blank_and_null_values_are_dropped(seed_label_rows, describe):
    """Empty entries left behind by the editor produce no lookup."""
    labels = describe(
        [{"name": "v", "field": "idDrug", "operator": "IN", "value": [None, ""]}]
    )

    assert labels == {}


def test_a_variable_without_ids_produces_no_group(seed_label_rows, describe):
    """Fields such as age carry a plain number, not a reference."""
    labels = describe([{"name": "v", "field": "age", "operator": ">=", "value": 65}])

    assert labels == {}


def test_an_unknown_field_produces_no_group(seed_label_rows, describe):
    """A field the backend does not map is skipped rather than guessed at."""
    labels = describe(
        [{"name": "v", "field": "zztUnknownField", "operator": "IN", "value": [1]}]
    )

    assert labels == {}


def test_a_null_variable_entry_is_tolerated(seed_label_rows, describe):
    """A null left in the variables array must not break the description."""
    labels = describe(
        [None, {"name": "v", "field": "idDrug", "operator": "IN", "value": [_DRUG[0]]}]
    )

    assert labels["drug"][str(_DRUG[0])] == _DRUG[1]


def test_the_same_id_referenced_twice_is_resolved_once(seed_label_rows, describe):
    """Two variables may point at the same row; the group holds one entry."""
    labels = describe(
        [
            {"name": "a", "field": "idDrug", "operator": "IN", "value": [_DRUG[0]]},
            {"name": "b", "field": "idDrug", "operator": "=", "value": _DRUG[0]},
        ]
    )

    assert labels["drug"] == {str(_DRUG[0]): _DRUG[1]}


def test_every_group_resolves_in_a_single_description(seed_label_rows, describe):
    """The realistic case: one protocol referencing every kind at once."""
    labels = describe(
        [
            {
                "name": "subs",
                "field": "substance",
                "operator": "IN",
                "value": [str(_SUBSTANCE[0])],
            },
            {
                "name": "cls",
                "field": "class",
                "operator": "IN",
                "value": [_CHILD_CLASS[0]],
            },
            {"name": "drug", "field": "idDrug", "operator": "IN", "value": [_DRUG[0]]},
            {"name": "icd", "field": "idIcd", "operator": "IN", "value": [_ICD[1]]},
            {
                "name": "dept",
                "field": "idDepartment",
                "operator": "IN",
                "value": [_DEPARTMENT[0]],
            },
            {
                "name": "seg",
                "field": "idSegment",
                "operator": "IN",
                "value": [_SEGMENT[0]],
            },
            {"name": "route", "field": "route", "operator": "IN", "value": [_ROUTE[0]]},
            {
                "name": "exam",
                "field": "exam",
                "operator": ">",
                "examType": _EXAM_TYPE[0],
                "value": 1,
            },
            {
                "name": "examref",
                "field": "exam_ref",
                "operator": ">",
                "examRefType": _GLOBAL_EXAM[0],
                "value": 1,
            },
        ]
    )

    assert set(labels.keys()) == {
        "substance",
        "class",
        "drug",
        "icd",
        "department",
        "segment",
        "route",
        "exam",
        "examRef",
    }
    assert labels["segment"][str(_SEGMENT[0])] == _SEGMENT[1]
    assert labels["substance"][str(_SUBSTANCE[0])] == _SUBSTANCE[1]
