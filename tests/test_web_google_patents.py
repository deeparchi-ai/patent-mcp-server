"""Tests for web.google_patents — regex, normalization, and parsers."""

from web.google_patents import (
    PATENT_NUMBER_RE,
    _ClaimParser,
    _MetaParser,
    _normalize_patent_number,
)


class TestNormalizePatentNumber:
    def test_us_patent_with_kind(self):
        assert _normalize_patent_number("US-7650331-B1") == "US-7650331-B1"

    def test_us_patent_without_kind(self):
        assert _normalize_patent_number("US7650331") == "US-7650331"

    def test_cn_patent_a(self):
        assert _normalize_patent_number("CN107452705A") == "CN-107452705-A"

    def test_cn_patent_b(self):
        assert _normalize_patent_number("CN-113257757-B") == "CN-113257757-B"

    def test_spaces_removed(self):
        assert _normalize_patent_number("CN 107452705 A") == "CN-107452705-A"

    def test_lowercase_input(self):
        assert _normalize_patent_number("cn107452705a") == "CN-107452705-A"

    def test_unrecognized_format_passthrough(self):
        assert _normalize_patent_number("garbage") == "garbage"


class TestPatentNumberRegex:
    def test_google_patents_url(self):
        m = PATENT_NUMBER_RE.search("https://patents.google.com/patent/CN107452705A/en")
        assert m is not None
        assert m.group(1) == "CN107452705A"

    def test_google_patents_url_with_dash(self):
        m = PATENT_NUMBER_RE.search(
            "https://patents.google.com/patent/US-7650331-B1/en"
        )
        assert m is not None
        # Regex captures up to the numbers, kind code after second dash is separate
        assert "7650331" in m.group(1)

    def test_wanfang_url(self):
        m = PATENT_NUMBER_RE.search("https://example.com/patent/CN202310083015.8")
        assert m is not None
        assert m.group(1) == "CN202310083015"

    def test_patent_equals_format(self):
        m = PATENT_NUMBER_RE.search("patent=CN1234567A&other=param")
        assert m is not None
        assert m.group(1) == "CN1234567A"

    def test_bare_cn_number_in_text(self):
        m = PATENT_NUMBER_RE.search("参见专利 CN103257828A 的相关内容")
        assert m is not None
        assert m.group(2) == "CN103257828A"

    def test_bare_cn_with_space(self):
        m = PATENT_NUMBER_RE.search("参考 CN 114287057 A 的实施例")
        assert m is not None
        # Kind code 'A' after space not captured — regex captures CN-number only
        assert m.group(2).startswith("CN")

    def test_no_false_positive_on_random_text(self):
        m = PATENT_NUMBER_RE.search("just some random text without patent numbers")
        assert m is None

    def test_finditer_multiple_patents(self):
        # CN at position 0 doesn't have [^/\\w] preceding char, so only the second matches.
        # Use a pattern with spaces to catch both.
        text = "Patent CN107452705A and CN114287057A are related"
        matches = list(PATENT_NUMBER_RE.finditer(text))
        assert len(matches) == 2
        assert matches[0].group(2) == "CN107452705A"
        assert matches[1].group(2) == "CN114287057A"


class TestMetaParser:
    def test_extracts_dc_meta_tags(self):
        html = (
            "<html><head>"
            '<meta name="DC.title" content="Test Patent Title">'
            '<meta name="DC.contributor" content="John Doe">'
            '<meta name="DC.contributor" content="ACME Corp">'
            "</head></html>"
        )
        parser = _MetaParser()
        parser.feed(html)
        assert parser.meta["DC.title"] == ["Test Patent Title"]
        assert parser.meta["DC.contributor"] == ["John Doe", "ACME Corp"]

    def test_extracts_itemprop_meta(self):
        html = '<meta itemprop="description" content="A patent about widgets">'
        parser = _MetaParser()
        parser.feed(html)
        assert parser.meta["description"] == ["A patent about widgets"]

    def test_empty_html(self):
        parser = _MetaParser()
        parser.feed("")
        assert parser.meta == {}


class TestClaimParser:
    def test_single_claim(self):
        html = '<div class="claim">1. A method comprising: doing something.</div>'
        parser = _ClaimParser()
        parser.feed(html)
        assert parser.claims == ["1. A method comprising: doing something."]

    def test_multiple_claims(self):
        html = (
            '<div class="claim">1. A widget comprising: a thing.</div>'
            '<div class="claim">2. The widget of claim 1, further comprising: another thing.</div>'
        )
        parser = _ClaimParser()
        parser.feed(html)
        assert len(parser.claims) == 2
        assert parser.claims[0] == "1. A widget comprising: a thing."

    def test_nested_divs_in_claim(self):
        html = '<div class="claim">1. A method <div>with nested</div> content.</div>'
        parser = _ClaimParser()
        parser.feed(html)
        assert parser.claims == ["1. A method with nested content."]

    def test_no_claims(self):
        html = "<div>No claims here</div>"
        parser = _ClaimParser()
        parser.feed(html)
        assert parser.claims == []
