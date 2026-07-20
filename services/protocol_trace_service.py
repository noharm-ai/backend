"""Service: protocol evaluation tracing (explains why protocols did/did not activate)"""

from datetime import datetime

from config import Config
from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import Protocol
from models.enums import NoHarmENV, ProtocolStatusTypeEnum, ProtocolTypeEnum
from models.main import Drug, Substance, User, db
from models.prescription import Prescription
from models.requests.protocol_request import ProtocolTraceRequest
from repository import protocol_repository
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
        drug_list=context["drug_list"], protocols=protocols
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
            trace = alert_protocol.evaluate_with_trace(protocol=protocol.config)
        except (ValueError, NotImplementedError) as error:
            date_groups.append(
                {
                    "date": expire_date,
                    "error": f"Configuração do protocolo inválida: {str(error)}",
                }
            )
            continue

        date_groups.append(
            {
                "date": expire_date,
                "activated": trace["activated"],
                "summary": build_summary(
                    activated=trace["activated"],
                    protocol_name=protocol.name,
                    substituted_trigger=trace["substituted_trigger"],
                ),
                "trigger": {
                    "expression": trace["trigger"],
                    "substituted": trace["substituted_trigger"],
                    "result": trace["activated"],
                },
                "result": trace["result"],
                "variableMessages": trace["variable_messages"],
                "relatedItems": trace["related_items"],
                "variables": [
                    variable_trace_to_dict(trace=v, name_lookup=name_lookup)
                    for v in trace["variables"]
                ],
            }
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


def _build_name_lookup(drug_list, protocols: list[Protocol]) -> dict:
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
    for protocol in protocols:
        config = protocol.config if protocol.config else {}
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
