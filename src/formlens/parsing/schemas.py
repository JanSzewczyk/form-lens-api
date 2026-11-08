"""The response of the parsing endpoint."""

from pydantic import BaseModel, Field


class ParseResponse(BaseModel):
    """The text extracted from one document."""

    text: str = Field(
        description="The text of the document, as Markdown or as plain text, depending on `format`.",
        examples=["# Invoice 2024-001\n\nTotal: 120.00 EUR"],
    )
    page_count: int = Field(description="Number of pages the model read.", examples=[1], ge=0)
    elapsed_ms: int = Field(description="Time the model took, in milliseconds.", examples=[8400], ge=0)
    model: str = Field(
        description="The model that read the document.", examples=["ibm-granite/granite-docling-258M-mlx"]
    )
