"""Tools: protocol creation co-pilot (Strands agent tools).

Each tool is a thin, read-only wrapper around an existing service function.
Tools run inside the Strands worker thread: the tenant schema is re-applied
defensively on every call and any failure is converted into an error tool
result so a broken lookup never aborts the chat turn.
"""

from strands import tool

from models.main import dbSession
from models.requests.protocol_request import (
    ProtocolTestRequest,
    ProtocolTestSampleRequest,
)
from services import (
    drug_service,
    exams_service,
    lists_service,
    protocol_trace_service,
    segment_service,
    substance_service,
)
from services.admin import admin_exam_service, admin_protocol_service
from utils import logger

MAX_RESULTS = 50
MAX_TEST_PRESCRIPTIONS = 3


def build_tools(schema: str, validate_config, normalize_config) -> list:
    """Build the co-pilot tool set bound to the tenant schema.

    validate_config: callable(config: dict, protocol_type: int) -> list[str]
    normalize_config: callable(config: dict) -> dict
    (both injected by the service to avoid a circular import).
    """

    def _success(result) -> dict:
        """Wrap a tool result in the success shape, truncating long lists."""
        if isinstance(result, list):
            result = result[:MAX_RESULTS]

        return {"status": "success", "content": [{"json": {"result": result}}]}

    def _run(fn, *args, **kwargs) -> dict:
        """Run a tool body with the tenant schema set; errors become tool errors."""
        try:
            dbSession.setSchema(schema)
            return _success(fn(*args, **kwargs))
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
        name="list_exam_types",
        description=(
            "Lista os tipos de exame do hospital. Retorna examType e nome. "
            "Use o examType em variáveis do tipo exam."
        ),
    )
    def list_exam_types() -> dict:
        """List schema exam types."""
        return _run(exams_service.list_exam_types)

    @tool(
        name="list_reference_exams",
        description=(
            "Lista exames de referência globais (com faixas normais). Retorna tpexam, "
            "nome e faixas. Use o tpexam em variáveis do tipo exam_ref."
        ),
    )
    def list_reference_exams() -> dict:
        """List global reference exams."""
        return _run(admin_exam_service.get_global_exams)

    @tool(
        name="list_departments",
        description=(
            "Lista os setores do hospital. Retorna idDepartment e nome. "
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
        list_exam_types,
        list_reference_exams,
        list_departments,
        list_segments,
        list_routes,
        validate_protocol,
        test_protocol,
    ]
