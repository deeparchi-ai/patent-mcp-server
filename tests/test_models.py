"""Tests for Pydantic patent data models."""

from datetime import date

# These will fail on first run — model classes not defined yet
from models.patent import (
    Citation,
    CitationGraph,
    ClassificationCode,
    PatentBasic,
    PatentDetail,
    PatentFamily,
)


class TestClassificationCode:
    def test_basic_cpc_code(self) -> None:
        c = ClassificationCode(code="G06F40/20", scheme="CPC", is_primary=True)
        assert c.code == "G06F40/20"
        assert c.scheme == "CPC"
        assert c.is_primary is True

    def test_defaults(self) -> None:
        c = ClassificationCode(code="H01L21/02", scheme="IPC")
        assert c.is_primary is False


class TestPatentBasic:
    def test_minimal_patent_basic(self) -> None:
        p = PatentBasic(
            publication_number="US-7650331-B1",
            title="Neural network training method",
            abstract="A method for training neural networks...",
            country_code="US",
        )
        assert p.publication_number == "US-7650331-B1"
        assert p.title == "Neural network training method"
        assert p.inventors == []
        assert p.cpc_codes == []
        assert p.url == "https://patents.google.com/patent/US-7650331-B1"

    def test_cn_patent_with_chinese_fields(self) -> None:
        p = PatentBasic(
            publication_number="CN-103257828-A",
            title="Multi-layer neural network accelerator",
            abstract="A multi-layer neural network accelerator...",
            country_code="CN",
            zh_title="多层神经网络加速器",
            zh_abstract="一种多层神经网络加速器...",
            assignee="华为技术有限公司",
        )
        assert p.country_code == "CN"
        assert p.zh_title == "多层神经网络加速器"
        assert p.zh_abstract == "一种多层神经网络加速器..."
        assert p.assignee == "华为技术有限公司"

    def test_dates_converted_from_int(self) -> None:
        p = PatentBasic(
            publication_number="US-7650331-B1",
            title="Test",
            abstract="Test",
            country_code="US",
            filing_date=date(2018, 6, 15),
            grant_date=date(2020, 3, 10),
        )
        assert p.filing_date == date(2018, 6, 15)
        assert p.grant_date == date(2020, 3, 10)

    def test_serialization_to_dict(self) -> None:
        p = PatentBasic(
            publication_number="US-7650331-B1",
            title="Test",
            abstract="Test",
            country_code="US",
            filing_date=date(2018, 6, 15),
            inventors=["John Doe"],
            cpc_codes=["G06F40/20"],
        )
        d = p.model_dump(mode="json")
        assert d["publication_number"] == "US-7650331-B1"
        assert d["inventors"] == ["John Doe"]
        assert d["filing_date"] == "2018-06-15"

    def test_empty_optional_fields_are_none(self) -> None:
        p = PatentBasic(
            publication_number="EP-1234567-A1",
            title="Test",
            abstract="Test",
            country_code="EP",
        )
        assert p.zh_title is None
        assert p.zh_abstract is None
        assert p.assignee is None
        assert p.filing_date is None
        assert p.grant_date is None


class TestPatentDetail:
    def test_extends_patent_basic(self) -> None:
        d = PatentDetail(
            publication_number="US-7650331-B1",
            title="Test",
            abstract="Test",
            country_code="US",
            family_id="12345",
            classifications=[ClassificationCode(code="G06F40/20", scheme="CPC")],
        )
        assert d.family_id == "12345"
        assert len(d.classifications) == 1
        assert isinstance(d.classifications[0], ClassificationCode)
        assert d.citations == []

    def test_includes_citations(self) -> None:
        d = PatentDetail(
            publication_number="US-7650331-B1",
            title="Test",
            abstract="Test",
            country_code="US",
            citations=[
                Citation(publication_number="US-1234567-A", category="X"),
                Citation(publication_number="US-8901234-B2", category="Y", type="EXA"),
            ],
        )
        assert len(d.citations) == 2
        assert d.citations[0].category == "X"
        assert d.citations[1].type == "EXA"

    def test_npl_citation(self) -> None:
        d = PatentDetail(
            publication_number="US-7650331-B1",
            title="Test",
            abstract="Test",
            country_code="US",
            citations=[
                Citation(
                    npl_text="Smith et al., 'Neural Networks', Journal of AI, 2017"
                ),
            ],
        )
        assert d.citations[0].publication_number is None
        assert (
            d.citations[0].npl_text
            == "Smith et al., 'Neural Networks', Journal of AI, 2017"
        )


class TestPatentFamily:
    def test_empty_family(self) -> None:
        f = PatentFamily(family_id="12345")
        assert f.family_id == "12345"
        assert f.members == []
        assert f.member_count == 0

    def test_family_with_members(self) -> None:
        members = [
            PatentBasic(
                publication_number="US-7650331-B1",
                title="Patent A",
                abstract="...",
                country_code="US",
                filing_date=date(2018, 1, 1),
            ),
            PatentBasic(
                publication_number="CN-103257828-A",
                title="Patent A CN",
                abstract="...",
                country_code="CN",
                filing_date=date(2019, 1, 1),
            ),
        ]
        f = PatentFamily(family_id="12345", members=members)
        assert f.member_count == 2


class TestCitationGraph:
    def test_empty_graph(self) -> None:
        g = CitationGraph(publication_number="US-7650331-B1")
        assert g.forward_citations == []
        assert g.backward_citations == []

    def test_full_graph(self) -> None:
        g = CitationGraph(
            publication_number="US-7650331-B1",
            forward_citations=[
                Citation(publication_number="US-9999999-A", category="A"),
            ],
            backward_citations=[
                Citation(publication_number="US-1111111-A", category="X"),
                Citation(publication_number="US-2222222-B2", category="Y", type="EXA"),
            ],
        )
        assert len(g.forward_citations) == 1
        assert len(g.backward_citations) == 2
        assert g.backward_citations[0].category == "X"  # fatal to novelty
