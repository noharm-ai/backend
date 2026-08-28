"""Service: protocol evaluation tracing (explains why protocols did/did not activate)"""

from datetime import datetime

from config import Config
from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import Protocol
from models.enums import NoHarmENV, ProtocolStatusTypeEnum, ProtocolTypeEnum
from models.main import Drug, Substance, User, db
from models.prescription import Prescription
from models.requests.prioritization_request import PrioritizationRequest
from models.requests.protocol_request import (
    ProtocolTestRequest,
    ProtocolTestSampleRequest,
    ProtocolTraceRequest,
)
from repository import prioritization_repository, protocol_repository
from services import alert_protocol_service, prescription_view_service
from utils import status
from utils.alert_protocol import AlertProtocol
from utils.alert_protocol_trace import build_summary, variable_trace_to_dict


@has_permission(Permission.READ_PRESCRIPTION)
def trace_protocol(request_data: ProtocolTraceRequest, user_context: User = None):
    """Re-runs protocol evaluation for a prescription with tracing enabled and
    returns a structured, user-friendly explanation per protocol"""

    context = prescription_view_service.get_protocol_evaluation_context(
        id_prescription=request_data.idPrescription, user_context=user_context
    )
    prescription: Prescription = context["prescription"]

    applicable_types = _get_applicable_types(prescription=prescription)

    if request_data.idProtocol is not None:
        protocol = protocol_repository.get_protocol_by_id(
            protocol_id=request_data.idProtocol, schema=user_context.schema
        )

        if protocol is None:
            raise ValidationError(
                "Protocolo inexistente",
                "errors.invalidRecord",
                status.HTTP_400_BAD_REQUEST,
            )

        protocols = [protocol]
    else:
        protocols = protocol_repository.get_active_protocols(
            schema=user_context.schema, protocol_type_list=applicable_types
        )

    drugs_by_expire_date = alert_protocol_service.split_drugs_by_date(
        drug_list=context["drug_list"], prescription=prescription
    )

    name_lookup = _build_name_lookup(
        drug_list=context["drug_list"],
        configs=[p.config for p in protocols],
    )

    return {
        "idPrescription": str(prescription.id),
        "evaluatedAt": datetime.now().isoformat(),
        "protocols": [
            _trace_single_protocol(
                protocol=protocol,
                context=context,
                drugs_by_expire_date=drugs_by_expire_date,
                applicable_types=applicable_types,
                name_lookup=name_lookup,
            )
            for protocol in protocols
        ],
    }


def _get_applicable_types(prescription: Prescription) -> list[ProtocolTypeEnum]:
    """Protocol types that run for this prescription (mirrors find_protocols)"""

    protocol_types = [
        ProtocolTypeEnum.PRESCRIPTION_ALL,
        ProtocolTypeEnum.PRESCRIPTION_ITEM,
    ]
    if prescription.agg:
        protocol_types.append(ProtocolTypeEnum.PRESCRIPTION_AGG)
    else:
        protocol_types.append(ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL)

    return protocol_types


def _get_applicability(
    protocol: Protocol, applicable_types: list[ProtocolTypeEnum]
) -> tuple[bool, list[str]]:
    """Checks if the protocol would run automatically for this prescription,
    returning user-friendly notes when it would not"""

    notes = []

    if protocol.status_type == ProtocolStatusTypeEnum.INACTIVE.value:
        notes.append("Este protocolo está inativo e não é executado automaticamente.")
    elif (
        protocol.status_type == ProtocolStatusTypeEnum.STAGING.value
        and Config.ENV == NoHarmENV.PRODUCTION.value
    ):
        notes.append(
            "Este protocolo está em homologação e não é executado em produção."
        )

    if protocol.protocol_type not in [t.value for t in applicable_types]:
        notes.append(
            "O tipo deste protocolo não se aplica a esta prescrição "
            "(ex.: protocolo de prescrição agregada em prescrição individual)."
        )

    return len(notes) == 0, notes


def _trace_single_protocol(
    protocol: Protocol,
    context: dict,
    drugs_by_expire_date: dict,
    applicable_types: list[ProtocolTypeEnum],
    name_lookup: dict,
) -> dict:
    """Evaluates one protocol with tracing inside each expire-date group"""

    applicable, applicability_notes = _get_applicability(
        protocol=protocol, applicable_types=applicable_types
    )

    date_groups = _evaluate_date_groups(
        config=protocol.config,
        protocol_name=protocol.name,
        context=context,
        drugs_by_expire_date=drugs_by_expire_date,
        name_lookup=name_lookup,
    )

    return {
        "idProtocol": protocol.id,
        "name": protocol.name,
        "protocolType": protocol.protocol_type,
        "statusType": protocol.status_type,
        "applicable": applicable,
        "applicabilityNotes": applicability_notes,
        "dateGroups": date_groups,
    }


def _evaluate_date_groups(
    config: dict,
    protocol_name: str,
    context: dict,
    drugs_by_expire_date: dict,
    name_lookup: dict | None = None,
    compact: bool = False,
) -> list[dict]:
    """Evaluates a protocol config with tracing inside each expire-date group.
    When compact, returns only date/activated/summary per group."""

    date_groups = []
    for expire_date, drugs in drugs_by_expire_date.items():
        alert_protocol = AlertProtocol(
            drugs=drugs,
            exams=context["exams"],
            prescription=context["prescription"],
            patient=context["patient"],
            cn_stats=context["cn_stats"],
            protocol_extra_info=context["protocol_extra_info"],
        )

        try:
            trace = alert_protocol.evaluate_with_trace(protocol=config)
        except (ValueError, NotImplementedError) as error:
            date_groups.append(
                {
                    "date": expire_date,
                    "error": f"Configuração do protocolo inválida: {str(error)}",
                }
            )
            continue

        group = {
            "date": expire_date,
            "activated": trace["activated"],
            "summary": build_summary(
                activated=trace["activated"],
                protocol_name=protocol_name,
                substituted_trigger=trace["substituted_trigger"],
            ),
        }

        if not compact:
            group.update(
                {
                    "trigger": {
                        "expression": trace["trigger"],
                        "substituted": trace["substituted_trigger"],
                        "result": trace["activated"],
                    },
                    "result": trace["result"],
                    "variableMessages": trace["variable_messages"],
                    "relatedItems": trace["related_items"],
                    "variables": [
                        variable_trace_to_dict(trace=v, name_lookup=name_lookup or {})
                        for v in trace["variables"]
                    ],
                }
            )

        date_groups.append(group)

    return date_groups


def _build_name_lookup(drug_list, configs: list[dict]) -> dict:
    """Maps substance/drug ids to names so trace messages show names instead of ids.
    Covers ids present in the prescription plus ids expected by the protocols."""

    substance_map = {}
    drug_map = {}

    for d in drug_list:
        prescription_drug = d[0]
        drug = d[1]
        substance = d[11]

        if substance is not None:
            substance_map[str(substance.id)] = substance.name

        if drug is not None and prescription_drug.idDrug is not None:
            drug_map[str(prescription_drug.idDrug)] = drug.name

    # ids referenced by protocol configs but absent from the prescription
    substance_ids = set()
    drug_ids = set()
    for config in configs:
        config = config if config else {}
        for variable in config.get("variables", []):
            field = variable.get("field")

            if field == "substance":
                substance_ids.update(str(v) for v in variable.get("value") or [])
            elif field == "idDrug":
                drug_ids.update(str(v) for v in variable.get("value") or [])
            elif field == "combination":
                substance_ids.update(str(v) for v in variable.get("substance") or [])
                drug_ids.update(str(v) for v in variable.get("drug") or [])

    substance_ids = {
        i for i in substance_ids if i not in substance_map and i.isdigit()
    }
    drug_ids = {i for i in drug_ids if i not in drug_map and i.isdigit()}

    if substance_ids:
        substances = (
            db.session.query(Substance)
            .filter(Substance.id.in_([int(i) for i in substance_ids]))
            .all()
        )
        for substance in substances:
            substance_map[str(substance.id)] = substance.name

    if drug_ids:
        drugs = (
            db.session.query(Drug)
            .filter(Drug.id.in_([int(i) for i in drug_ids]))
            .all()
        )
        for drug in drugs:
            drug_map[str(drug.id)] = drug.name

    return {"substance": substance_map, "drug": drug_map}


def _protocol_type_to_agg(protocol_type: int) -> bool:
    """Prescription kind a protocol type runs on (mirrors _get_applicable_types)"""

    return protocol_type != ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL.value


@has_permission(Permission.WRITE_PROTOCOLS)
def sample_prescriptions(
    request_data: ProtocolTestSampleRequest, user_context: User = None
):
    """Samples prescriptions of the current day compatible with a protocol type,
    so an unsaved protocol config can be tested against them in chunks"""

    prioritization_request = PrioritizationRequest(
        agg=_protocol_type_to_agg(request_data.protocolType),
        idSegment=request_data.idSegment,
    )

    ids = prioritization_repository.sample_prescription_ids(
        request=prioritization_request, limit=request_data.limit
    )

    return {"idPrescriptionList": [str(i) for i in ids], "total": len(ids)}


@has_permission(Permission.WRITE_PROTOCOLS)
def test_protocol(request_data: ProtocolTestRequest, user_context: User = None):
    """Evaluates an unsaved protocol config against a chunk of real prescriptions.
    No status gating: this is an explicit test, so the config always runs;
    protocol type compatibility is reported as an informational flag"""

    config = request_data.config.model_dump()
    evaluated_at = datetime.now().isoformat()

    return {
        "evaluatedAt": evaluated_at,
        "results": [
            _test_single_prescription(
                id_prescription=id_prescription,
                config=config,
                request_data=request_data,
                evaluated_at=evaluated_at,
                user_context=user_context,
            )
            for id_prescription in request_data.idPrescriptionList
        ],
    }


def _test_single_prescription(
    id_prescription: int,
    config: dict,
    request_data: ProtocolTestRequest,
    evaluated_at: str,
    user_context: User,
) -> dict:
    """Evaluates the config under test against one prescription.
    Errors are reported per prescription so one bad id does not fail the chunk"""

    try:
        context = prescription_view_service.get_protocol_evaluation_context(
            id_prescription=id_prescription, user_context=user_context
        )
    except ValidationError as error:
        return {"idPrescription": str(id_prescription), "error": str(error)}

    prescription: Prescription = context["prescription"]
    applicable_types = _get_applicable_types(prescription=prescription)
    type_match = request_data.protocolType in [t.value for t in applicable_types]

    drugs_by_expire_date = alert_protocol_service.split_drugs_by_date(
        drug_list=context["drug_list"], prescription=prescription
    )

    name_lookup = None
    if request_data.detailed:
        name_lookup = _build_name_lookup(
            drug_list=context["drug_list"], configs=[config]
        )

    date_groups = _evaluate_date_groups(
        config=config,
        protocol_name=request_data.name,
        context=context,
        drugs_by_expire_date=drugs_by_expire_date,
        name_lookup=name_lookup,
        compact=not request_data.detailed,
    )

    result = {
        "idPrescription": str(prescription.id),
        "typeMatch": type_match,
        "activated": any(g.get("activated") for g in date_groups),
        "dateGroups": [
            {
                "date": g.get("date"),
                "activated": g.get("activated"),
                "summary": g.get("summary"),
                "error": g.get("error"),
            }
            for g in date_groups
        ],
        "error": None,
    }

    if request_data.detailed:
        applicability_notes = []
        if not type_match:
            applicability_notes.append(
                "O tipo deste protocolo não se aplica a esta prescrição "
                "(ex.: protocolo de prescrição agregada em prescrição individual)."
            )

        result["trace"] = {
            "idPrescription": str(prescription.id),
            "evaluatedAt": evaluated_at,
            "protocols": [
                {
                    "idProtocol": 0,
                    "name": request_data.name,
                    "protocolType": request_data.protocolType,
                    "statusType": ProtocolStatusTypeEnum.STAGING.value,
                    "applicable": type_match,
                    "applicabilityNotes": applicability_notes,
                    "dateGroups": date_groups,
                }
            ],
        }

    return result
