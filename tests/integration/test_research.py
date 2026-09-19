from pydantic import ValidationError
import pytest

from operator_api import extraction, research
from operator_api.schemas import CompanyResearch, ResearchClaim


COMPANY_PAGE = """
<html>
  <head>
    <title>Northstar | About</title>
    <meta name="description" content="Northstar builds dependable data systems.">
    <script type="application/ld+json">
      {"@type":"Organization","description":"We help teams operate critical infrastructure."}
    </script>
  </head>
</html>
"""


def test_company_research_uses_exact_official_source_excerpts(monkeypatch):
    job = extraction.parse(
        "https://jobs.example/role",
        """<script type="application/ld+json">
        {"@type":"JobPosting","title":"Engineer","hiringOrganization":{
          "name":"Northstar","sameAs":"https://northstar.example/about"}}
        </script>""",
    )
    monkeypatch.setattr(
        research.extraction,
        "fetch",
        lambda _url: ("https://northstar.example/about", COMPANY_PAGE),
    )

    result = research.company(job)

    assert str(job.company_url) == "https://northstar.example/about"
    assert [claim.text for claim in result.claims] == [
        "Northstar builds dependable data systems.",
        "We help teams operate critical infrastructure.",
    ]
    assert len(result.sources) == 1
    assert result.sources[0].title == "Northstar | About"
    assert str(result.sources[0].url) == "https://northstar.example/about"
    assert {claim.source_id for claim in result.claims} == {result.sources[0].id}


def test_company_research_falls_back_when_fetch_fails(monkeypatch):
    job = extraction.parse(
        "https://jobs.example/role",
        """<script type="application/ld+json">
        {"@type":"JobPosting","title":"Engineer","hiringOrganization":{
          "name":"Northstar","url":"https://northstar.example"}}
        </script>""",
    )

    def fail(_url):
        raise OSError("offline")

    monkeypatch.setattr(research.extraction, "fetch", fail)
    assert research.company(job) == CompanyResearch(company="Northstar")


def test_company_research_rejects_claim_without_source():
    with pytest.raises(ValidationError, match="unknown source"):
        CompanyResearch(
            company="Northstar",
            claims=[ResearchClaim(text="Unsupported", source_id="missing")],
        )
