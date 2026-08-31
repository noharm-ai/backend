"""Integration tests for the protocol tracing and testing endpoints
(protocol_trace_service): /protocol/prescription-trace, /protocol/test/sample
and /protocol/test.

Tracing replays the protocol evaluation of a real prescription and explains,
per protocol and per expire-date group, why it did or did not activate. The
test endpoints do the same for a protocol config that is still being edited
and has not been saved yet.
"""

import json

import pytest
from sqlalchemy import bindparam, text

from models.enums import ProtocolStatusTypeEnum, ProtocolTypeEnum
from tests.conftest import session, session_commit
from tests.utils import utils_test_prescription

# create_basic_prescription always prescribes these two drugs
_DRUG_IN_PRESCRIPTION = 3
_DRUG_NOT_IN_PRESCRIPTION = 999999

# Protocol rows live in the shared public.protocolo table; the 991xxx range
# belongs to this file only.
_ACTIVATED_ID = 991001
_NOT_ACTIVATED_ID = 991002
_INACTIVE_ID = 991003
_AGG_TYPE_ID = 991004
_BROKEN_CONFIG_ID = 991005
_OTHER_SCHEMA_ID = 991006

_ALL_IDS = (
    _ACTIVATED_ID,
    _NOT_ACTIVATED_ID,
    _INACTIVE_ID,
    _AGG_TYPE_ID,
    _BROKEN_CONFIG_ID,
    _OTHER_SCHEMA_ID,
)

_RESULT = {"type": "SHOW_MESSAGE", "level": "high", "message": "ZZTest alerta"}


def _config(trigger: str, variables: list[dict]) -> dict:
    """Protocol configuration in the shape stored in protocolo.configuracao."""
    return {"trigger": trigger, "variables": variables, "result": _RESULT}


def _drug_variable(name: str, id_drug: int) -> dict:
    """Variable that is true when the prescription contains the drug."""
    return {"name": name, "field": "idDrug", "operator": "IN", "value": [str(id_drug)]}


_ACTIVATED_CONFIG = _config(
    "{{presente}}", [_drug_variable("presente", _DRUG_IN_PRESCRIPTION)]
)
_NOT_ACTIVATED_CONFIG = _config(
    "{{presente}} and {{ausente}}",
    [
        _drug_variable("presente", _DRUG_IN_PRESCRIPTION),
        _drug_variable("ausente", _DRUG_NOT_IN_PRESCRIPTION),
    ],
)
# an unknown field makes the evaluation raise, which the trace reports per group
_BROKEN_CONFIG = _config(
    "{{quebrado}}",
    [{"name": "quebrado", "field": "unknownField", "operator": "IN", "value": ["1"]}],
)

# (id, schema, name, protocol type, status, config)
_PROTOCOL_ROWS = (
    (
        _ACTIVATED_ID,
        "demo",
        "ZZTest Ativado",
        ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL.value,
        ProtocolStatusTypeEnum.ACTIVE.value,
        _ACTIVATED_CONFIG,
    ),
    (
        _NOT_ACTIVATED_ID,
        "demo",
        "ZZTest Nao Ativado",
        ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL.value,
        ProtocolStatusTypeEnum.ACTIVE.value,
        _NOT_ACTIVATED_CONFIG,
    ),
    (
        _INACTIVE_ID,
        "demo",
        "ZZTest Inativo",
        ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL.value,
        ProtocolStatusTypeEnum.INACTIVE.value,
        _ACTIVATED_CONFIG,
    ),
    (
        _AGG_TYPE_ID,
        "demo",
        "ZZTest Agregada",
        ProtocolTypeEnum.PRESCRIPTION_AGG.value,
        ProtocolStatusTypeEnum.ACTIVE.value,
        _ACTIVATED_CONFIG,
    ),
    (
        _BROKEN_CONFIG_ID,
        "demo",
        "ZZTest Config Invalida",
        ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL.value,
        ProtocolStatusTypeEnum.ACTIVE.value,
        _BROKEN_CONFIG,
    ),
    (
        _OTHER_SCHEMA_ID,
        "other-schema",
        "ZZTest Outro Schema",
        ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL.value,
        ProtocolStatusTypeEnum.ACTIVE.value,
        _ACTIVATED_CONFIG,
    ),
)


@pytest.fixture(scope="module")
def traced_prescription():
    """An individual prescription of the current day, with two drugs."""
    return utils_test_prescription.create_basic_prescription()


@pytest.fixture
def seed_trace_protocols():
    """Protocols covering activation, non-activation and applicability cases."""
    for id_protocol, schema, name, protocol_type, status_type, config in _PROTOCOL_ROWS:
        session.execute(
            text(
                "INSERT INTO public.protocolo "
                "(idprotocolo, schema_name, nome, tp_protocolo, tp_situacao, "
                "configuracao, created_at, created_by) "
                "VALUES (:id, :schema, :name, :protocol_type, :status_type, "
                "CAST(:config AS json), now(), 1)"
            ),
            {
                "id": id_protocol,
                "schema": schema,
                "name": name,
                "protocol_type": protocol_type,
                "status_type": status_type,
                "config": json.dumps(config),
            },
        )
    session_commit()

    yield

    session.execute(
        text("DELETE FROM public.protocolo WHERE idprotocolo IN :ids").bindparams(
            bindparam("ids", expanding=True)
        ),
        {"ids": list(_ALL_IDS)},
    )
    session_commit()


def _trace(client, headers, id_prescription, id_protocol=None):
    """Call the trace endpoint for one prescription."""
    url = f"/protocol/prescription-trace?idPrescription={id_prescription}"
    if id_protocol is not None:
        url += f"&idProtocol={id_protocol}"

    return client.get(url, headers=headers)


def _protocols_by_id(response):
    """Traced protocols indexed by protocol id."""
    return {
        item["idProtocol"]: item for item in response.get_json()["data"]["protocols"]
    }


def _single_group(protocol):
    """The only expire-date group of a non-aggregated prescription."""
    assert len(protocol["dateGroups"]) == 1
    return protocol["dateGroups"][0]


# --- /protocol/prescription-trace ---------------------------------------------


def test_trace_allowed_for_viewer(client, viewer_headers, traced_prescription):
    """VIEWER carries READ_PRESCRIPTION, so the trace is readable."""
    response = _trace(client, viewer_headers, traced_prescription.id)

    assert response.status_code == 200


def test_trace_denied_without_read_prescription(
    client, user_manager_headers, traced_prescription
):
    """A user without READ_PRESCRIPTION cannot trace a prescription [401]."""
    response = _trace(client, user_manager_headers, traced_prescription.id)

    assert response.status_code == 401


def test_trace_unknown_prescription(client, analyst_headers):
    """An unknown prescription id is rejected [400]."""
    response = _trace(client, analyst_headers, 999999999)

    assert response.status_code == 400


def test_trace_requires_id_prescription(client, analyst_headers):
    """idPrescription is mandatory [400]."""
    response = client.get("/protocol/prescription-trace", headers=analyst_headers)

    assert response.status_code == 400


def test_trace_returns_visible_protocols(
    client, analyst_headers, traced_prescription, seed_trace_protocols
):
    """Every protocol that runs for the prescription type is traced."""
    response = _trace(client, analyst_headers, traced_prescription.id)

    assert response.status_code == 200
    data = response.get_json()["data"]

    assert data["idPrescription"] == str(traced_prescription.id)
    assert data["evaluatedAt"]

    by_id = _protocols_by_id(response)
    # individual-type protocols of the schema are evaluated...
    assert _ACTIVATED_ID in by_id
    assert _NOT_ACTIVATED_ID in by_id
    # ...an inactive one, another schema's and an aggregated-type one are not
    assert _INACTIVE_ID not in by_id
    assert _OTHER_SCHEMA_ID not in by_id
    assert _AGG_TYPE_ID not in by_id


def test_trace_explains_an_activated_protocol(
    client, analyst_headers, traced_prescription, seed_trace_protocols
):
    """An activated protocol reports its trigger, result and variables."""
    response = _trace(
        client, analyst_headers, traced_prescription.id, id_protocol=_ACTIVATED_ID
    )

    assert response.status_code == 200
    protocol = _protocols_by_id(response)[_ACTIVATED_ID]

    assert protocol["name"] == "ZZTest Ativado"
    assert protocol["applicable"] is True
    assert protocol["applicabilityNotes"] == []

    group = _single_group(protocol)
    assert group["activated"] is True
    assert group["trigger"]["expression"] == "{{presente}}"
    assert group["trigger"]["substituted"] == "True"
    assert group["result"]["message"] == _RESULT["message"]
    assert [v["name"] for v in group["variables"]] == ["presente"]
    assert group["variables"][0]["result"] is True


def test_trace_explains_a_non_activated_protocol(
    client, analyst_headers, traced_prescription, seed_trace_protocols
):
    """A non-activated protocol points at the variable that turned false."""
    response = _trace(
        client, analyst_headers, traced_prescription.id, id_protocol=_NOT_ACTIVATED_ID
    )

    assert response.status_code == 200
    group = _single_group(_protocols_by_id(response)[_NOT_ACTIVATED_ID])

    assert group["activated"] is False
    assert group["result"] is None
    assert group["trigger"]["substituted"] == "True and False"

    false_variables = [v for v in group["variables"] if not v["result"]]
    assert [v["name"] for v in false_variables] == ["ausente"]


def test_trace_resolves_drug_names(
    client, analyst_headers, traced_prescription, seed_trace_protocols
):
    """Ids in the trace messages are replaced by the drug names."""
    response = _trace(
        client, analyst_headers, traced_prescription.id, id_protocol=_ACTIVATED_ID
    )

    assert response.status_code == 200
    variable = _single_group(_protocols_by_id(response)[_ACTIVATED_ID])["variables"][0]

    # the id is rendered as the drug name taken from the prescription
    assert str(_DRUG_IN_PRESCRIPTION) not in variable["message"]
    assert "ANLODIPINO" in variable["message"].upper()


def test_trace_reports_inactive_protocol_as_not_applicable(
    client, analyst_headers, traced_prescription, seed_trace_protocols
):
    """Tracing an inactive protocol explains it never runs automatically."""
    response = _trace(
        client, analyst_headers, traced_prescription.id, id_protocol=_INACTIVE_ID
    )

    assert response.status_code == 200
    protocol = _protocols_by_id(response)[_INACTIVE_ID]

    assert protocol["applicable"] is False
    assert any("inativo" in note for note in protocol["applicabilityNotes"])
    # it is still evaluated, so the user can see what it would have done
    assert _single_group(protocol)["activated"] is True


def test_trace_reports_incompatible_protocol_type(
    client, analyst_headers, traced_prescription, seed_trace_protocols
):
    """An aggregated-type protocol does not apply to an individual prescription."""
    response = _trace(
        client, analyst_headers, traced_prescription.id, id_protocol=_AGG_TYPE_ID
    )

    assert response.status_code == 200
    protocol = _protocols_by_id(response)[_AGG_TYPE_ID]

    assert protocol["applicable"] is False
    assert any("tipo" in note for note in protocol["applicabilityNotes"])


def test_trace_reports_invalid_config_per_group(
    client, analyst_headers, traced_prescription, seed_trace_protocols
):
    """A config the evaluator cannot run is reported instead of failing [200]."""
    response = _trace(
        client, analyst_headers, traced_prescription.id, id_protocol=_BROKEN_CONFIG_ID
    )

    assert response.status_code == 200
    group = _single_group(_protocols_by_id(response)[_BROKEN_CONFIG_ID])

    assert "error" in group
    assert "Configuração do protocolo inválida" in group["error"]


def test_trace_unknown_protocol(client, analyst_headers, traced_prescription):
    """An unknown protocol id is rejected [400]."""
    response = _trace(
        client, analyst_headers, traced_prescription.id, id_protocol=999999999
    )

    assert response.status_code == 400


def test_trace_hides_other_schema_protocol(
    client, analyst_headers, traced_prescription, seed_trace_protocols
):
    """A protocol owned by another schema cannot be traced [400]."""
    response = _trace(
        client, analyst_headers, traced_prescription.id, id_protocol=_OTHER_SCHEMA_ID
    )

    assert response.status_code == 400


# --- /protocol/test/sample ----------------------------------------------------


def test_sample_permission_denied(client, analyst_headers):
    """Sampling prescriptions requires WRITE_PROTOCOLS [401]."""
    response = client.post(
        "/protocol/test/sample",
        json={"protocolType": ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL.value},
        headers=analyst_headers,
    )

    assert response.status_code == 401


def test_sample_returns_individual_prescriptions(
    client, admin_headers, traced_prescription
):
    """An individual-type protocol samples non-aggregated prescriptions."""
    response = client.post(
        "/protocol/test/sample",
        json={
            "protocolType": ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL.value,
            "idSegment": traced_prescription.idSegment,
            "limit": 200,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200
    data = response.get_json()["data"]

    assert str(traced_prescription.id) in data["idPrescriptionList"]
    assert data["total"] == len(data["idPrescriptionList"])


def test_sample_excludes_aggregated_when_type_is_individual(
    client, admin_headers, traced_prescription
):
    """An aggregated-type protocol does not sample individual prescriptions."""
    response = client.post(
        "/protocol/test/sample",
        json={
            "protocolType": ProtocolTypeEnum.PRESCRIPTION_AGG.value,
            "idSegment": traced_prescription.idSegment,
            "limit": 200,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert (
        str(traced_prescription.id)
        not in response.get_json()["data"]["idPrescriptionList"]
    )


def test_sample_respects_limit(client, admin_headers, traced_prescription):
    """limit caps how many prescriptions come back."""
    response = client.post(
        "/protocol/test/sample",
        json={
            "protocolType": ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL.value,
            "limit": 1,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert len(response.get_json()["data"]["idPrescriptionList"]) <= 1


def test_sample_rejects_limit_above_maximum(client, admin_headers):
    """The sample size is bounded by the request model [400]."""
    response = client.post(
        "/protocol/test/sample",
        json={
            "protocolType": ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL.value,
            "limit": 500,
        },
        headers=admin_headers,
    )

    assert response.status_code == 400


# --- /protocol/test -----------------------------------------------------------


def _test_body(config, id_prescription, **extra):
    """Body for the unsaved-config test endpoint."""
    body = {
        "config": config,
        "protocolType": ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL.value,
        "idPrescriptionList": [id_prescription],
    }
    body.update(extra)

    return body


def test_test_protocol_permission_denied(client, analyst_headers, traced_prescription):
    """Testing a config requires WRITE_PROTOCOLS [401]."""
    response = client.post(
        "/protocol/test",
        json=_test_body(_ACTIVATED_CONFIG, traced_prescription.id),
        headers=analyst_headers,
    )

    assert response.status_code == 401


def test_test_protocol_compact_result(client, admin_headers, traced_prescription):
    """By default each prescription reports only whether the config activated."""
    response = client.post(
        "/protocol/test",
        json=_test_body(_ACTIVATED_CONFIG, traced_prescription.id),
        headers=admin_headers,
    )

    assert response.status_code == 200
    data = response.get_json()["data"]

    assert data["evaluatedAt"]
    assert len(data["results"]) == 1

    result = data["results"][0]
    assert result["idPrescription"] == str(traced_prescription.id)
    assert result["activated"] is True
    assert result["typeMatch"] is True
    assert result["error"] is None
    # the compact shape carries no trace and no variable detail
    assert "trace" not in result
    assert set(result["dateGroups"][0]) == {"date", "activated", "summary", "error"}


def test_test_protocol_not_activated(client, admin_headers, traced_prescription):
    """A config whose trigger stays false reports activated=False."""
    response = client.post(
        "/protocol/test",
        json=_test_body(_NOT_ACTIVATED_CONFIG, traced_prescription.id),
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["results"][0]["activated"] is False


def test_test_protocol_detailed_result(client, admin_headers, traced_prescription):
    """detailed adds the full trace, in the same shape as the trace endpoint."""
    response = client.post(
        "/protocol/test",
        json=_test_body(_ACTIVATED_CONFIG, traced_prescription.id, detailed=True),
        headers=admin_headers,
    )

    assert response.status_code == 200
    result = response.get_json()["data"]["results"][0]

    trace = result["trace"]
    assert trace["idPrescription"] == str(traced_prescription.id)

    protocol = trace["protocols"][0]
    # an unsaved config has no id yet and is reported as staging
    assert protocol["idProtocol"] == 0
    assert protocol["name"] == "Protocolo em teste"
    assert protocol["statusType"] == ProtocolStatusTypeEnum.STAGING.value
    assert protocol["applicable"] is True

    group = protocol["dateGroups"][0]
    assert group["activated"] is True
    assert [v["name"] for v in group["variables"]] == ["presente"]


def test_test_protocol_uses_the_given_name(client, admin_headers, traced_prescription):
    """The name under test shows up in the trace and in the group summary."""
    response = client.post(
        "/protocol/test",
        json=_test_body(
            _ACTIVATED_CONFIG,
            traced_prescription.id,
            detailed=True,
            name="ZZTest Rascunho",
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200
    protocol = response.get_json()["data"]["results"][0]["trace"]["protocols"][0]

    assert protocol["name"] == "ZZTest Rascunho"
    assert "ZZTest Rascunho" in protocol["dateGroups"][0]["summary"]


def test_test_protocol_reports_incompatible_type(
    client, admin_headers, traced_prescription
):
    """A type mismatch is informational: the config still runs."""
    response = client.post(
        "/protocol/test",
        json=_test_body(
            _ACTIVATED_CONFIG,
            traced_prescription.id,
            protocolType=ProtocolTypeEnum.PRESCRIPTION_AGG.value,
            detailed=True,
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200
    result = response.get_json()["data"]["results"][0]

    assert result["typeMatch"] is False
    assert result["activated"] is True
    assert result["trace"]["protocols"][0]["applicabilityNotes"]


def test_test_protocol_reports_invalid_config_per_group(
    client, admin_headers, traced_prescription
):
    """A config the evaluator cannot run reports the error, not a 500."""
    response = client.post(
        "/protocol/test",
        json=_test_body(_BROKEN_CONFIG, traced_prescription.id),
        headers=admin_headers,
    )

    assert response.status_code == 200
    result = response.get_json()["data"]["results"][0]

    assert result["activated"] is False
    assert "Configuração do protocolo inválida" in result["dateGroups"][0]["error"]


def test_test_protocol_isolates_a_bad_prescription_id(
    client, admin_headers, traced_prescription
):
    """One unknown id does not break the rest of the chunk."""
    response = client.post(
        "/protocol/test",
        json={
            "config": _ACTIVATED_CONFIG,
            "protocolType": ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL.value,
            "idPrescriptionList": [traced_prescription.id, 999999999],
        },
        headers=admin_headers,
    )

    assert response.status_code == 200
    results = response.get_json()["data"]["results"]

    assert results[0]["activated"] is True
    assert results[1]["idPrescription"] == "999999999"
    assert results[1]["error"]


def test_test_protocol_requires_a_prescription(client, admin_headers):
    """An empty prescription list is rejected by the request model [400]."""
    response = client.post(
        "/protocol/test",
        json={
            "config": _ACTIVATED_CONFIG,
            "protocolType": ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL.value,
            "idPrescriptionList": [],
        },
        headers=admin_headers,
    )

    assert response.status_code == 400


def test_test_protocol_limits_the_chunk_size(client, admin_headers):
    """At most ten prescriptions can be evaluated per call [400]."""
    response = client.post(
        "/protocol/test",
        json={
            "config": _ACTIVATED_CONFIG,
            "protocolType": ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL.value,
            "idPrescriptionList": list(range(1, 12)),
        },
        headers=admin_headers,
    )

    assert response.status_code == 400


def test_test_protocol_rejects_incomplete_config(client, admin_headers):
    """A config missing the trigger is rejected by the request model [400]."""
    response = client.post(
        "/protocol/test",
        json={
            "config": {"variables": [], "result": _RESULT},
            "protocolType": ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL.value,
            "idPrescriptionList": [1],
        },
        headers=admin_headers,
    )

    assert response.status_code == 400
