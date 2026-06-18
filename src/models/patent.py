"""Pydantic models for patent data."""

from datetime import date

from pydantic import BaseModel, Field, computed_field


class ClassificationCode(BaseModel):
    """Patent classification code (CPC, IPC, USPC, FI, F-term)."""

    code: str
    scheme: str = "CPC"
    is_primary: bool = False


class Citation(BaseModel):
    """Patent or NPL citation with X/Y/A/D category markers."""

    publication_number: str | None = None
    category: str | None = None  # X, Y, A, D, E, P, O, T
    type: str | None = None  # EXA, APP, ISR, SEA, OPP
    npl_text: str | None = None  # non-patent literature text


class PatentBasic(BaseModel):
    """Patent search result summary."""

    publication_number: str
    title: str
    abstract: str
    country_code: str

    zh_title: str | None = None
    zh_abstract: str | None = None
    filing_date: date | None = None
    grant_date: date | None = None
    assignee: str | None = None
    inventors: list[str] = Field(default_factory=list)
    cpc_codes: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def url(self) -> str:
        return f"https://patents.google.com/patent/{self.publication_number}"


class PatentDetail(PatentBasic):
    """Full patent detail including classifications and citations."""

    kind_code: str | None = None
    application_number: str | None = None
    family_id: str | None = None
    priority_date: date | None = None
    entity_status: str | None = None
    art_unit: str | None = None
    classifications: list[ClassificationCode] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


class PatentFamily(BaseModel):
    """Simple patent family: all publications sharing the same family_id."""

    family_id: str
    members: list[PatentBasic] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def member_count(self) -> int:
        return len(self.members)


class CitationGraph(BaseModel):
    """Forward and backward citations for a patent."""

    publication_number: str
    forward_citations: list[Citation] = Field(default_factory=list)
    backward_citations: list[Citation] = Field(default_factory=list)
