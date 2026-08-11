"""Response: structured output classes for the protocol creation co-pilot agent"""

from typing import Optional

from pydantic import BaseModel, Field


class ProtocolAgentProposalConfig(BaseModel):
    """Proposed protocol configuration (same shape persisted in Protocol.config)."""

    variables: list[dict] = Field(
        description=(
            "Variáveis do protocolo. Cada item: name, field, operator, value e "
            "campos extras do tipo (examType, examPeriod, examRefType, "
            "examRefPeriod, statsType). Variáveis do tipo combination não têm "
            "operator nem value: cada critério (substance, drug, class, route, "
            "dose, doseOperator...) é uma chave direta da variável, nunca um "
            "objeto aninhado"
        )
    )
    trigger: str = Field(
        description="Expressão de gatilho combinando {{nome}} com and/or/not e parênteses"
    )
    result: dict = Field(
        description="Alerta exibido: type (SHOW_MESSAGE), level (low|medium|high), message, description"
    )


class ProtocolAgentProposal(BaseModel):
    """Complete protocol draft proposed by the agent."""

    name: Optional[str] = Field(default=None, description="Nome sugerido do protocolo")
    protocolType: Optional[int] = Field(
        default=None,
        description="Tipo do protocolo: 1 agregada, 2 individual, 3 todas, 4 item prescrito",
    )
    config: ProtocolAgentProposalConfig


class ProtocolAgentTurnOutput(BaseModel):
    """Structured output of one co-pilot chat turn."""

    message: str = Field(
        description=(
            "Resposta em português (PT-BR) exibida ao usuário no chat, em HTML "
            "simples. Use apenas as tags <p>, <br>, <strong>, <em>, <ul>, <ol>, "
            "<li>, <code>, sempre envolvendo os parágrafos em <p>. Nunca use "
            "Markdown, outras tags ou atributos"
        )
    )
    proposal: Optional[ProtocolAgentProposal] = Field(
        default=None,
        description=(
            "Proposta completa de protocolo quando houver informação suficiente; "
            "null quando a resposta for apenas uma pergunta ou explicação"
        ),
    )
