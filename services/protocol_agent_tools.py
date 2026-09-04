"""Tools: protocol creation co-pilot (Strands agent tools).

Each tool is a thin, read-only wrapper around an existing service function.
Tools run inside the Strands worker thread: the tenant schema is re-applied
defensively on every call and any failure is converted into an error tool
result so a broken lookup never aborts the chat turn.
"""

from strands import tool

from models.main import dbSession
from models.enums import TagTypeEnum
from models.requests.protocol_request import (
    ProtocolTestRequest,
    ProtocolTestSampleRequest,
)
from models.requests.tag_request import TagListRequest
from repository import exams_repository, tag_repository
from services import (
    clinical_notes_service,
    drug_service,
    lists_service,
    protocol_trace_service,
    segment_service,
    substance_service,
)
from services.admin import admin_protocol_service
from utils import logger

MAX_RESULTS = 50
MAX_EXAM_TYPE_RESULTS = 200
MAX_REFERENCE_EXAM_RESULTS = 25
MAX_TEST_PRESCRIPTIONS = 3


def _filter_items(items: list, term: str, keys: tuple) -> list:
    """Case-insensitive substring filter over the given keys of each item."""
    if not term:
        return items

    needle = str(term).strip().lower()
    if not needle:
        return items

    return [
        item
        for item in items
        if any(needle in str(item.get(key) or "").lower() for key in keys)
    ]


def _success(result, max_results: int = MAX_RESULTS) -> dict:
    """Wrap a tool result in the success shape.

    A truncated list used to be indistinguishable from a complete one, which is
    what pushed the agent to invent ids it could not find: the catalog listings
    are ordered by name, so anything past the cap simply did not exist as far as
    the model could tell. Lists now report the total and an explicit truncated
    flag so the agent knows to narrow its search term instead of guessing.
    Non-list results (validate_protocol, test_protocol) pass through unwrapped.
    """
    if isinstance(result, list):
        items = result[:max_results]
        result = {
            "items": items,
            "returned": len(items),
            "total": len(result),
            "truncated": len(result) > len(items),
        }

    return {"status": "success", "content": [{"json": {"result": result}}]}


def build_tools(schema: str, validate_config, normalize_config) -> list:
    """Build the co-pilot tool set bound to the tenant schema.

    validate_config: callable(config: dict, protocol_type: int) -> list[str]
    normalize_config: callable(config: dict) -> dict
    (both injected by the service to avoid a circular import).
    """

    def _run(fn, *args, max_results: int = MAX_RESULTS, **kwargs) -> dict:
        """Run a tool body with the tenant schema set; errors become tool errors."""
        try:
            dbSession.setSchema(schema)
            return _success(fn(*args, **kwargs), max_results=max_results)
        except Exception as error:
            logger.backend_logger.warning(
                "Protocol agent tool error: %s", str(error)[:500]
            )
            return {
                "status": "error",
                "content": [{"text": f"Erro na ferramenta: {str(error)[:300]}"}],
            }

    @tool(
        name="search_substances",
        description=(
            "Busca substâncias pelo nome (parcial). Retorna sctid e nome. "
            "Use o sctid como valor em variáveis do tipo substance."
        ),
    )
    def search_substances(term: str) -> dict:
        """Search substances by name."""
        return _run(substance_service.find_substance, term)

    @tool(
        name="search_substance_classes",
        description=(
            "Busca classes de substância pelo nome (parcial). Retorna id e nome. "
            "Use o id como valor em variáveis do tipo class."
        ),
    )
    def search_substance_classes(term: str) -> dict:
        """Search substance classes by name."""
        return _run(substance_service.find_substance_class, term)

    @tool(
        name="search_drugs",
        description=(
            "Busca medicamentos do hospital pelo nome (parcial). Retorna idDrug e nome. "
            "Use o idDrug como valor em variáveis do tipo idDrug."
        ),
    )
    def search_drugs(term: str) -> dict:
        """Search hospital drugs by name."""
        return _run(drug_service.find_protocol_drugs, term)

    @tool(
        name="search_icds",
        description=(
            "Busca CIDs por código ou descrição. Retorna id e nome. "
            "Use o id como valor em variáveis do tipo idIcd."
        ),
    )
    def search_icds(term: str) -> dict:
        """Search ICDs by code or description."""
        return _run(lists_service.find_icds, term)

    @tool(
        name="search_exam_types",
        description=(
            "Busca os tipos de exame do hospital pelo nome ou pelo próprio examType "
            "(parcial). Omita o termo para listar todos. Retorna examType e nome. "
            "Use o examType, sempre em minúsculas, em variáveis do tipo exam."
        ),
    )
    def search_exam_types(term: str = None) -> dict:
        """Search schema exam types."""

        # Read the repository directly instead of exams_service.list_exam_types:
        # that service hides the calculated exams (ckd21, mdrd...) which are
        # valid at runtime, and this is the same source the proposal validator
        # checks against, so anything findable here passes validation.
        def _list():
            items = [
                {"examType": r.typeExam.lower(), "name": r.name}
                for r in exams_repository.get_exam_types()
            ]
            return _filter_items(items, term, ("examType", "name"))

        return _run(_list, max_results=MAX_EXAM_TYPE_RESULTS)

    @tool(
        name="search_reference_exams",
        description=(
            "Busca exames de referência globais pelo nome, abreviação ou tpexam "
            "(parcial). Omita o termo para listar todos. ATENÇÃO: o valor do campo "
            "tpexam é o que deve ser escrito em examRefType, copiado exatamente como "
            "retornado, inclusive maiúsculas e minúsculas. Prefira exames com "
            "configuredInThisHospital=true: os demais nunca produzem resultado neste "
            "hospital."
        ),
    )
    def search_reference_exams(term: str = None) -> dict:
        """Search global reference exams."""

        def _list():
            configured = set(exams_repository.get_configured_exam_ref_types())
            items = [
                {
                    "tpexam": e.tp_exam,
                    "name": e.name,
                    "initials": e.initials,
                    "measureUnit": e.measureunit,
                    "configuredInThisHospital": e.tp_exam in configured,
                }
                for e in exams_repository.get_global_exams()
            ]
            return _filter_items(items, term, ("tpexam", "name", "initials"))

        return _run(_list, max_results=MAX_REFERENCE_EXAM_RESULTS)

    @tool(
        name="list_departments",
        description=(
            "Lista os setores do hospital. Retorna idDepartment, nome e os "
            "segmentos aos quais o setor pertence. "
            "Use o idDepartment em variáveis do tipo idDepartment."
        ),
    )
    def list_departments() -> dict:
        """List departments."""
        return _run(admin_protocol_service.list_departments)

    @tool(
        name="list_segments",
        description=(
            "Lista os segmentos do hospital. Retorna id e descrição. "
            "Use o id em variáveis do tipo idSegment."
        ),
    )
    def list_segments() -> dict:
        """List segments."""

        def _list():
            return [
                {"id": s.id, "description": s.description}
                for s in segment_service.get_segments()
            ]

        return _run(_list)

    @tool(
        name="list_routes",
        description=(
            "Lista as vias de administração. Retorna id e nome. "
            "Use o id em variáveis do tipo route."
        ),
    )
    def list_routes() -> dict:
        """List administration routes."""
        return _run(lists_service.list_routes)

    @tool(
        name="list_tags",
        description=(
            "Lista os marcadores de paciente ativos. Retorna name (nome do "
            "marcador). Use o name em variáveis do tipo tags."
        ),
    )
    def list_tags() -> dict:
        """List active patient tags."""

        def _list():
            request_data = TagListRequest(
                active=True,
                tagTypeList=[
                    TagTypeEnum.PATIENT.value,
                    TagTypeEnum.PATIENT_NAVIGATION.value,
                ],
            )
            return [
                {"name": t.name, "tagType": t.tag_type}
                for t in tag_repository.list_tags(request_data=request_data)
            ]

        return _run(_list)

    @tool(
        name="list_stats_types",
        description=(
            "Lista os indicadores NoHarm Care. Retorna statsType e nome. "
            "Use o statsType em variáveis do tipo cn_stats."
        ),
    )
    def list_stats_types() -> dict:
        """List clinical notes stats indicators."""

        def _list():
            return [
                {"statsType": tag["key"], "name": tag["name"]}
                for tag in clinical_notes_service.get_tags()
            ]

        return _run(_list)

    @tool(
        name="validate_protocol",
        description=(
            "Valida uma configuração de protocolo (variables, trigger, result) para um "
            "protocolType. Retorna a lista de erros (vazia quando válida). "
            "SEMPRE valide antes de apresentar uma proposta ao usuário."
        ),
    )
    def validate_protocol(config: dict, protocol_type: int) -> dict:
        """Validate an unsaved protocol config."""

        def _validate():
            errors = validate_config(config=config, protocol_type=protocol_type)
            return {"valid": not errors, "errors": errors}

        return _run(_validate)

    @tool(
        name="test_protocol",
        description=(
            "Testa uma configuração de protocolo contra prescrições reais do dia "
            "(máximo 3). Informe id_prescription_list para testar prescrições "
            "específicas ou omita para amostrar automaticamente."
        ),
    )
    def test_protocol(
        config: dict, protocol_type: int, id_prescription_list: list[int] = None
    ) -> dict:
        """Evaluate an unsaved protocol config against real prescriptions."""

        def _test():
            # Same normalization applied to a proposal: the evaluator reads the
            # combination criteria as flat keys, so a nested combo would be
            # tested as an empty one and match every item.
            normalized_config = normalize_config(config)
            ids = id_prescription_list
            if not ids:
                sample = protocol_trace_service.sample_prescriptions(
                    request_data=ProtocolTestSampleRequest(
                        protocolType=protocol_type, limit=MAX_TEST_PRESCRIPTIONS
                    )
                )
                ids = [int(i) for i in sample.get("idPrescriptionList", [])]

            if not ids:
                return {"message": "Nenhuma prescrição disponível para teste hoje"}

            return protocol_trace_service.test_protocol(
                request_data=ProtocolTestRequest(
                    config=normalized_config,
                    protocolType=protocol_type,
                    idPrescriptionList=ids[:MAX_TEST_PRESCRIPTIONS],
                    detailed=False,
                )
            )

        return _run(_test)

    return [
        search_substances,
        search_substance_classes,
        search_drugs,
        search_icds,
        search_exam_types,
        search_reference_exams,
        list_departments,
        list_segments,
        list_routes,
        list_tags,
        list_stats_types,
        validate_protocol,
        test_protocol,
    ]
