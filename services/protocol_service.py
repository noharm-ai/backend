"""Service: protocol related operations"""

from sqlalchemy import func

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import Department, ICDTable
from models.enums import MemoryEnum
from models.main import Drug, Substance, SubstanceClass, User, db
from models.requests.protocol_request import (
    ProtocolDescriptionRequest,
    ProtocolListRequest,
)
from models.segment import Segment
from repository import exams_repository, protocol_repository
from services import memory_service
from utils import status


@has_permission(Permission.READ_BASIC_FEATURES)
def list_protocols(request_data: ProtocolListRequest, user_context: User):
    """List protocols and filter"""
    results = protocol_repository.list_protocols(
        request_data=request_data, schema=user_context.schema
    )

    protocols = []
    for item in results:
        protocols.append(
            {
                "id": item.id,
                "name": item.name,
                "protocolType": item.protocol_type,
                "status": item.status_type,
            }
        )

    return protocols


# Variable field -> label group. Mirrors the frontend LabelKind union so the
# client can look a description up as labels[kind][str(id)].
_FIELD_KINDS = {
    "substance": "substance",
    "class": "class",
    "idDrug": "drug",
    "idIcd": "icd",
    "idDepartment": "department",
    "idSegment": "segment",
    "route": "route",
}


@has_permission(Permission.READ_PRESCRIPTION)
def describe_protocol(request_data: ProtocolDescriptionRequest, user_context: User):
    """Trigger expression and variables of a protocol, plus the descriptions
    behind every id they reference, so the prescription view can render the rule
    in plain language for end users.

    Status is deliberately not filtered: any protocol visible to the schema can
    be described, active or not.
    """

    protocol = protocol_repository.get_protocol_by_id(
        protocol_id=request_data.idProtocol, schema=user_context.schema
    )

    if protocol is None:
        raise ValidationError(
            "Protocolo inexistente",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    config = protocol.config if protocol.config else {}
    variables = config.get("variables") or []

    return {
        "id": protocol.id,
        "name": protocol.name,
        "protocolType": protocol.protocol_type,
        "trigger": config.get("trigger"),
        "onlyLatestExpireDate": bool(config.get("onlyLatestExpireDate", False)),
        "variables": variables,
        "labels": _build_variable_labels(variables),
    }


def _collect_ids(variables: list[dict]) -> dict:
    """Group the ids referenced by the variables by label group"""

    ids = {}

    def add(kind: str, values):
        if not values:
            return

        if not isinstance(values, list):
            values = [values]

        for value in values:
            if value is None or value == "":
                continue

            ids.setdefault(kind, set()).add(str(value))

    for variable in variables:
        variable = variable if variable else {}
        field = variable.get("field")

        if field == "combination":
            add("substance", variable.get("substance"))
            add("class", variable.get("class"))
            add("drug", variable.get("drug"))
            # combination routes are free text typed by the user, already readable
            continue

        if field == "exam":
            add("exam", variable.get("examType"))
            continue

        if field == "exam_ref":
            add("examRef", variable.get("examRefType"))
            continue

        kind = _FIELD_KINDS.get(field)
        if kind:
            add(kind, variable.get("value"))

    return ids


def _numeric(ids: set) -> list[int]:
    """Ids that can be compared against an integer column"""

    return [int(i) for i in ids if str(i).lstrip("-").isdigit()]


def _build_variable_labels(variables: list[dict]) -> dict:
    """Resolve id -> description for every id the variables reference.

    Descriptions are plain names (no id prefix): this payload is rendered for
    end users, who read "Vancomicina", not "1234 - Vancomicina".

    Drug, department and segment ids live in schema-scoped tables, so they
    resolve against the caller's schema. For a global protocol (schema_name
    NULL) that is the same assumption the protocol editor makes when it resolves
    the very same ids through /drugs/resolve and the department listing, so both
    audiences read a config the same way. Ids with no match are left out and the
    client falls back to showing the id.
    """

    ids = _collect_ids(variables)
    labels = {}

    if ids.get("substance"):
        rows = (
            db.session.query(Substance)
            .filter(Substance.id.in_(_numeric(ids["substance"])))
            .all()
        )
        labels["substance"] = {str(r.id): r.name for r in rows}

    if ids.get("class"):
        parent = db.aliased(SubstanceClass)
        rows = (
            db.session.query(SubstanceClass, parent.name.label("parent_name"))
            .outerjoin(parent, SubstanceClass.idParent == parent.id)
            .filter(SubstanceClass.id.in_([str(i) for i in ids["class"]]))
            .all()
        )
        labels["class"] = {
            str(r[0].id): f"{r[1]} - {r[0].name}" if r[1] else r[0].name for r in rows
        }

    if ids.get("drug"):
        rows = db.session.query(Drug).filter(Drug.id.in_(_numeric(ids["drug"]))).all()
        labels["drug"] = {str(r.id): r.name for r in rows}

    if ids.get("icd"):
        rows = (
            db.session.query(ICDTable)
            .filter(ICDTable.id_str.in_([str(i) for i in ids["icd"]]))
            .all()
        )
        labels["icd"] = {r.id_str: f"{r.id_str} - {r.name}" for r in rows}

    if ids.get("department"):
        # the same fksetor may exist once per hospital, possibly with different
        # names; dedupe the same way the department listing does
        rows = (
            db.session.query(Department.id, func.min(Department.name).label("name"))
            .filter(Department.id.in_(_numeric(ids["department"])))
            .group_by(Department.id)
            .all()
        )
        labels["department"] = {str(r.id): r.name for r in rows}

    if ids.get("segment"):
        rows = (
            db.session.query(Segment)
            .filter(Segment.id.in_(_numeric(ids["segment"])))
            .all()
        )
        labels["segment"] = {str(r.id): r.description for r in rows}

    if ids.get("route"):
        map_routes = memory_service.get_memory(MemoryEnum.MAP_ROUTES.value)
        routes = {}
        if map_routes and map_routes.value:
            for route in map_routes.value:
                if isinstance(route, dict) and route.get("id") is not None:
                    route_id = str(route.get("id"))
                    if route_id in ids["route"]:
                        routes[route_id] = route.get("value") or route_id
        labels["route"] = routes

    if ids.get("exam"):
        labels["exam"] = {
            e.typeExam: e.name
            for e in exams_repository.get_exam_types()
            if e.typeExam in ids["exam"]
        }

    if ids.get("examRef"):
        labels["examRef"] = {
            e.tp_exam: e.name
            for e in exams_repository.get_global_exams()
            if e.tp_exam in ids["examRef"]
        }

    return labels
