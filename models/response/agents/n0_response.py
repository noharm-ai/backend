"""Response: response classes for n0_agent"""

from pydantic import BaseModel, Field


class ExtraFields(BaseModel):
    """Campos complementares."""

    label: str = Field(description="Descrição do campo")
    type: str = Field(description="Tipo de campo (text, boolean, archive)")


class TicketForm(BaseModel):
    """Complete person information."""

    type: str = Field(description="tipo de chamado")
    subject: str = Field(description="Assunto do chamado")
    description: str = Field(description="Descrição do chamado")
    extra_fields: list[ExtraFields] = Field(
        description="Campos complementares necessários para escalar o chamado",
    )
