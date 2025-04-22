"""Service: admin protocol operations"""

from datetime import datetime, timedelta
from collections import namedtuple

from decorators.has_permission_decorator import has_permission, Permission
from repository import protocol_repository
from models.main import User, db, Drug, DrugAttributes, Substance
from models.appendix import Protocol, Frequency
from models.prescription import Prescription, PrescriptionDrug
from models.requests.protocol_request import ProtocolListRequest, ProtocolUpsertRequest
from models.enums import ProtocolStatusTypeEnum, ProtocolVariableFieldEnum
from utils import dateutils, status
from utils.alert_protocol import AlertProtocol
from exception.validation_error import ValidationError


@has_permission(Permission.READ_PROTOCOLS)
def list_protocols(request_data: ProtocolListRequest, user_context: User):
    """List schema protocols"""
    results = protocol_repository.list_protocols(
        request_data=request_data, schema=user_context.schema
    )

    protocols = []
    for item in results:
        protocols.append(
            {
                "id": item.id,
                "name": item.name,
                "schema": item.schema,
                "protocolType": item.protocol_type,
                "config": item.config,
                "statusType": item.status_type,
                "createdAt": dateutils.to_iso(item.created_at),
                "updatedAt": dateutils.to_iso(item.updated_at),
            }
        )

    return protocols


@has_permission(Permission.WRITE_PROTOCOLS)
def upsert_protocol(request_data: ProtocolUpsertRequest, user_context: User):
    """Upsert protocol records"""

    if request_data.id:
        protocol = (
            db.session.query(Protocol).filter(Protocol.id == request_data.id).first()
        )

        if not protocol:
            raise ValidationError(
                "Registro de protocolo inválido",
                "errors.businessRules",
                status.HTTP_400_BAD_REQUEST,
            )

        if protocol.schema != user_context.schema:
            raise ValidationError(
                "Registro de protocolo inválido (schema)",
                "errors.businessRules",
                status.HTTP_400_BAD_REQUEST,
            )

        protocol.updated_at = datetime.today()
        protocol.updated_by = user_context.id

    else:
        protocol = Protocol()
        protocol.schema = user_context.schema
        protocol.created_at = datetime.today()
        protocol.created_by = user_context.id
        db.session.add(protocol)

    if request_data.statusType == ProtocolStatusTypeEnum.ACTIVE.value:
        raise ValidationError(
            "Protocolo não pode ser ativado pela interface",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    _validate_variables(variables=request_data.config.variables)
    _test_protocol(protocol=request_data.config.model_dump())

    protocol.name = request_data.name
    protocol.status_type = request_data.statusType
    protocol.protocol_type = request_data.protocolType
    protocol.config = request_data.config.model_dump()

    db.session.flush()

    return protocol.id


def _validate_variables(variables: list[dict]):
    valid_operators = [
        ">",
        "<",
        ">=",
        "<=",
        "=",
        "!=",
        "IN",
        "NOTIN",
    ]

    if not variables:
        raise ValidationError(
            "Nenhuma variável foi definida",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    for var in variables:
        name = var.get("name", None)
        field = var.get("field", None)
        operator = var.get("operator", None)
        exam_type = var.get("examType", None)
        exam_period = var.get("examPeriod", None)
        value = var.get("value", None)

        if not name:
            raise ValidationError(
                "Nome de variável inválido",
                "errors.businessRules",
                status.HTTP_400_BAD_REQUEST,
            )

        if not field:
            raise ValidationError(
                f"Variável {name}: Campo Tipo é obrigatório",
                "errors.businessRules",
                status.HTTP_400_BAD_REQUEST,
            )

        if field not in [item.value for item in ProtocolVariableFieldEnum]:
            raise ValidationError(
                f"Variável {name}: Tipo inválido",
                "errors.businessRules",
                status.HTTP_400_BAD_REQUEST,
            )

        if field == ProtocolVariableFieldEnum.EXAM.value and not exam_type:
            raise ValidationError(
                f"Variável {name}: Tipo exame inválido",
                "errors.businessRules",
                status.HTTP_400_BAD_REQUEST,
            )

        if "examPeriod" in var and (exam_period is None or exam_period == ""):
            var.pop("examPeriod")

        if field == ProtocolVariableFieldEnum.COMBINATION.value:
            combo_fields = [
                "substance",
                "drug",
                "class",
                "dose",
                "doseOperator",
                "frequencyday",
                "frequencydayOperator",
                "route",
                "period",
                "periodOperator",
            ]

            for cf in combo_fields:
                if cf not in var:
                    continue

                cf_value = var.get(cf, None)

                if not cf_value:
                    var.pop(cf)
                elif "Operator" in cf and cf_value not in valid_operators:
                    raise ValidationError(
                        f"Variável {name}: Operador inválido ({cf})",
                        "errors.businessRules",
                        status.HTTP_400_BAD_REQUEST,
                    )

        else:
            if not operator or not value:
                raise ValidationError(
                    f"Variável {name}: Todos os campos são obrigatórios",
                    "errors.businessRules",
                    status.HTTP_400_BAD_REQUEST,
                )

            if operator not in valid_operators:
                raise ValidationError(
                    f"Variável {name}: Operador inválido",
                    "errors.businessRules",
                    status.HTTP_400_BAD_REQUEST,
                )

            if operator in ["IN", "NOTIN"] and not isinstance(value, list):
                raise ValidationError(
                    f"Variável {name}: Valor deve ser uma lista",
                    "errors.businessRules",
                    status.HTTP_400_BAD_REQUEST,
                )

            if operator not in ["IN", "NOTIN"] and isinstance(value, list):
                raise ValidationError(
                    f"Variável {name}: Valor não deve ser uma lista",
                    "errors.businessRules",
                    status.HTTP_400_BAD_REQUEST,
                )


def _test_protocol(protocol: dict):
    drug_list = [
        _get_prescription_drug_mock_row(
            id_prescription_drug=1,
            dose=10,
            drug_name="Drug A",
            drug_class="J1",
            route="IV",
        ),
        _get_prescription_drug_mock_row(
            id_prescription_drug=2,
            dose=20,
            drug_name="Drug B",
            drug_class="J2",
            route="IV",
        ),
        _get_prescription_drug_mock_row(
            id_prescription_drug=3,
            dose=20,
            drug_name="Drug C",
            drug_class="J3",
            route="ORAL",
        ),
    ]

    prescription = Prescription()
    prescription.idDepartment = 100
    prescription.idSegment = 1
    exams = {
        "age": 50,
        "weight": 80,
        "ckd21": {
            "value": 3.2,
            "date": (datetime.today().date() - timedelta(days=3)).isoformat(),
        },
    }
    alert_protocol = AlertProtocol(
        drugs=drug_list, exams=exams, prescription=prescription
    )
    try:
        alert_protocol.get_protocol_alerts(protocol=protocol)
    except Exception as e:
        raise ValidationError(
            f"Gatilho possui formato inválido: {str(e)}",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )


def _get_prescription_drug_mock_row(
    id_prescription_drug: int,
    dose: float,
    frequency: float = None,
    max_dose: float = None,
    kidney: float = None,
    liver: float = None,
    platelets: float = None,
    elderly: bool = None,
    tube: bool = None,
    allergy: str = None,
    drug_name: str = "Test2",
    pregnant: str = None,
    lactating: str = None,
    interval: str = None,
    freq_obj: Frequency = None,
    use_weight: bool = False,
    expire_date: datetime = None,
    intravenous: bool = False,
    group: str = None,
    solutionGroup: bool = False,
    idPrescription: str = None,
    drug_class: str = None,
    sctid: str = None,
    route: str = None,
):
    MockRow = namedtuple(
        "Mockrow",
        "prescription_drug drug measure_unit frequency not_used score drug_attributes notes prevnotes status expire substance period_cpoe prescription_date measure_unit_convert_factor substance_handling_types",
    )

    sctid = (
        sctid if sctid else f"{id_prescription_drug}11111"
    )  # Generate a unique sctid
    d = Drug()
    d.id = id_prescription_drug
    d.name = drug_name
    d.sctid = sctid

    pd = PrescriptionDrug()
    pd.id = id_prescription_drug
    pd.source = "Medicamentos"
    pd.idDrug = 1
    pd.frequency = frequency
    pd.doseconv = dose
    pd.tube = tube
    pd.allergy = allergy
    pd.interval = interval
    pd.intravenous = intravenous
    pd.group = group
    pd.solutionGroup = solutionGroup
    pd.idPrescription = idPrescription
    pd.route = route

    da = DrugAttributes()
    da.idDrug = id_prescription_drug
    da.idSegment = 1
    da.maxDose = max_dose
    da.kidney = kidney
    da.liver = liver
    da.platelets = platelets
    da.elderly = elderly
    da.tube = tube
    da.pregnant = pregnant
    da.lactating = lactating
    da.fasting = True
    da.useWeight = use_weight

    substance = Substance()
    substance.id = sctid
    substance.idclass = drug_class

    return MockRow(
        pd,
        d,
        None,
        freq_obj,
        None,
        None,
        da,
        None,
        None,
        None,
        expire_date or datetime.now() + timedelta(days=1),
        substance,
        0,
        datetime.now(),
        1,
        [],
    )
