"""Bounded, official-URL company research with exact source excerpts."""

import hashlib
import json
from html.parser import HTMLParser

from . import extraction
from .db import utcnow
from .schemas import CompanyResearch, JobPosting, ResearchClaim, Source


class CompanyPageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title_parts = []
        self.in_title = False
        self.descriptions = []
        self.script = None
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag.casefold() == "title":
            self.in_title = True
        if tag.casefold() == "meta" and values.get("name", "").casefold() == "description":
            if values.get("content"):
                self.descriptions.append(values["content"])
        if tag.casefold() == "script" and values.get("type", "").casefold() == "application/ld+json":
            self.script = []

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)
        if self.script is not None:
            self.script.append(data)

    def handle_endtag(self, tag):
        if tag.casefold() == "title":
            self.in_title = False
        if tag.casefold() == "script" and self.script is not None:
            self.scripts.append("".join(self.script))
            self.script = None


def _organization_descriptions(scripts):
    for script in scripts:
        try:
            for node in extraction.nodes(json.loads(script)):
                kinds = node.get("@type", [])
                kinds = [kinds] if isinstance(kinds, str) else kinds
                if "Organization" in kinds:
                    value = extraction.plain(node.get("description"))
                    if value:
                        yield value
        except (ValueError, RecursionError):
            continue


def company(job: JobPosting) -> CompanyResearch:
    if not job.company_url:
        return CompanyResearch(company=job.company)
    try:
        final_url, html = extraction.fetch(str(job.company_url))
    except Exception:
        return CompanyResearch(company=job.company)
    parser = CompanyPageParser()
    parser.feed(html)
    excerpts = []
    for value in [*parser.descriptions, *_organization_descriptions(parser.scripts)]:
        cleaned = extraction.plain(value)[:2000]
        if cleaned and cleaned not in excerpts:
            excerpts.append(cleaned)
    if not excerpts:
        return CompanyResearch(company=job.company)
    source_id = "company-" + hashlib.sha256(html.encode()).hexdigest()[:20]
    source = Source(
        id=source_id,
        url=final_url,
        title=extraction.plain(" ".join(parser.title_parts)) or job.company,
        excerpt="\n".join(excerpts),
        retrieved_at=utcnow(),
    )
    return CompanyResearch(
        company=job.company,
        claims=[ResearchClaim(text=value, source_id=source_id) for value in excerpts[:3]],
        sources=[source],
    )
