"""Bounded HTTPS ingestion using a pinned public address and JSON-LD JobPosting data."""

import hashlib
from datetime import date
from html.parser import HTMLParser
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit
from uuid import uuid4
from .db import utcnow
from .schemas import EligibilityRequirements, JobPosting, Requirement, Source

MAX_BYTES = 2_000_000


def public_target(url):
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.port not in (None, 443)
    ):
        raise ValueError("Only public HTTPS job pages on port 443 without embedded credentials are supported")
    addresses = sorted(
        {item[4][0] for item in socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)}
    )
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("Local, private, and reserved network destinations are blocked")
    return parts, addresses[0]


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, hostname, address, timeout):
        super().__init__(hostname, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        # Connect to the validated literal address; retain original host for certificate/SNI verification.
        raw = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def fetch(url):
    deadline = time.monotonic() + 20
    for _ in range(4):
        parts, address = public_target(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("Job page retrieval timed out")
        connection = PinnedHTTPS(parts.hostname, address, min(5, remaining))
        try:
            connection.request(
                "GET",
                (parts.path or "/") + ("?" + parts.query if parts.query else ""),
                headers={"Accept": "text/html", "Accept-Encoding": "identity", "User-Agent": "Operator/0.1"},
            )
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location:
                    raise ValueError("Redirect has no destination")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError(f"Job page returned HTTP {response.status}")
            if "text/html" not in (response.getheader("Content-Type") or "").casefold():
                raise ValueError("Job URL must return an HTML page")
            if (response.getheader("Content-Encoding") or "identity") != "identity":
                raise ValueError("Compressed responses are not supported")
            chunks, size = [], 0
            while True:
                if time.monotonic() > deadline:
                    raise ValueError("Job page retrieval timed out")
                block = response.read1(min(65536, MAX_BYTES + 1 - size))
                if not block:
                    break
                size += len(block)
                if size > MAX_BYTES:
                    raise ValueError("Job page exceeds the 2 MB limit")
                chunks.append(block)
            return url, b"".join(chunks).decode("utf-8", errors="replace")
        finally:
            connection.close()
    raise ValueError("Job page exceeded the redirect limit")


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag.casefold() == "script" and dict(attrs).get("type", "").casefold() == "application/ld+json":
            self.current = []

    def handle_data(self, text):
        if self.current is not None:
            self.current.append(text)

    def handle_endtag(self, tag):
        if tag.casefold() == "script" and self.current is not None:
            self.scripts.append("".join(self.current))
            self.current = None


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []

    def handle_data(self, text):
        self.text.append(text)


def plain(value):
    if not isinstance(value, str):
        return ""
    parser = TextParser()
    parser.feed(value)
    return " ".join(" ".join(parser.text).split())


def nodes(value):
    if isinstance(value, list):
        for item in value:
            yield from nodes(item)
    elif isinstance(value, dict):
        yield value
        if "@graph" in value:
            yield from nodes(value["@graph"])


_YEAR_IN_TEXT = re.compile(r"(20\d{2}|19[89]\d)")
_GRAD_CUTOFF = re.compile(
    r"(?:class\s+of|graduat\w*|before|by)\s*:?\s*(20\d{2}|19[89]\d)"
    r"|(20\d{2}|19[89]\d)\s*(?:or\s+earlier|or\s+before)",
    re.I,
)
_YEARS_EXPERIENCE = re.compile(r"(\d+(?:\.\d+)?)\s*\+?\s*years?", re.I)


def _plain_values(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _plain_values(item)
    elif isinstance(value, dict):
        for key in ("name", "credentialCategory", "description", "text"):
            item = value.get(key)
            if isinstance(item, str):
                yield item


def _parse_iso_date(value):
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _experience_years_min(value):
    if isinstance(value, dict):
        months = value.get("monthsOfExperience")
        if isinstance(months, (int, float)) and months >= 0:
            return round(months / 12, 1)
        for text in _plain_values(value):
            years = _experience_years_min(text)
            if years is not None:
                return years
        return None
    if isinstance(value, list):
        for item in value:
            years = _experience_years_min(item)
            if years is not None:
                return years
        return None
    if isinstance(value, str):
        match = _YEARS_EXPERIENCE.search(value)
        return float(match.group(1)) if match else None
    return None


def _graduation_year_max(value):
    for text in _plain_values(value):
        match = _GRAD_CUTOFF.search(text)
        if match:
            return int(match.group(1) or match.group(2))
        if re.search(r"or\s+earlier|or\s+before", text, re.I):
            year = _YEAR_IN_TEXT.search(text)
            if year:
                return int(year.group(1))
    return None


def _work_authorizations(value):
    names = []
    for text in _plain_values(value):
        cleaned = " ".join(text.split())
        if cleaned and cleaned not in names:
            names.append(cleaned)
    return names or None


def _employment_types(value):
    types = []
    for text in _plain_values(value):
        types.append(text.strip().casefold())
    return types


def _extract_eligibility(posting: dict, source_id: str) -> EligibilityRequirements | None:
    """Copy explicit JSON-LD hard constraints; do not infer bounds from titles or deadlines."""
    fields: dict = {}
    experience = _experience_years_min(posting.get("experienceRequirements"))
    if experience is not None:
        fields["experience_years_min"] = experience
    graduation = _graduation_year_max(posting.get("educationRequirements"))
    if graduation is not None:
        fields["graduation_year_max"] = graduation
    authorizations = _work_authorizations(posting.get("eligibilityToWorkRequirement"))
    if authorizations:
        fields["accepted_work_authorizations"] = authorizations
    intern = any("intern" in item for item in _employment_types(posting.get("employmentType")))
    start = _parse_iso_date(posting.get("jobStartDate"))
    end = _parse_iso_date(posting.get("jobEndDate"))
    if intern and start and end:
        fields["internship_start"] = start
        fields["internship_end"] = end
    if not fields:
        return None
    try:
        return EligibilityRequirements(**fields, source_ids=[source_id])
    except Exception:
        return None


def parse(url, html):
    parser = PageParser()
    parser.feed(html)
    postings = []
    for script in parser.scripts:
        try:
            for node in nodes(json.loads(script)):
                kinds = node.get("@type", [])
                if isinstance(kinds, str):
                    kinds = [kinds]
                if "JobPosting" in kinds:
                    postings.append(node)
        except (ValueError, RecursionError):
            continue
    if len(postings) != 1:
        raise ValueError(
            "Expected one JSON-LD JobPosting; unsupported or ambiguous page. Use a supported job-detail page."
        )
    posting = postings[0]
    title = plain(posting.get("title"))
    organization = posting.get("hiringOrganization")
    company = plain(organization.get("name")) if isinstance(organization, dict) else ""
    if not title or not company:
        raise ValueError("Job posting must specify a title and hiring organization")
    sid = "source-" + hashlib.sha256(html.encode()).hexdigest()[:20]
    source = Source(
        id=sid, url=url, title=title, excerpt=plain(posting.get("description"))[:20000], retrieved_at=utcnow()
    )
    requirements = []
    for field, category in (
        ("skills", "skill"),
        ("qualifications", "education"),
        ("experienceRequirements", "experience"),
    ):
        values = posting.get(field, [])
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            continue
        for value in values[:50]:
            text = plain(value)
            if text:
                rid = hashlib.sha256((field + text).encode()).hexdigest()[:20]
                requirements.append(
                    Requirement(
                        id=rid, text=text[:2000], category=category, importance="required", source_id=sid
                    )
                )
    # Keep explicit excerpts for each requirement; the raw snapshot remains available.
    source.excerpt += "\n" + "\n".join(requirement.text for requirement in requirements)
    location = None
    if posting.get("jobLocationType") == "TELECOMMUTE":
        location = "Remote"
    elif isinstance(posting.get("jobLocation"), dict):
        address = posting["jobLocation"].get("address", {})
        if isinstance(address, dict):
            location = plain(address.get("addressLocality")) or None
    eligibility_requirements = _extract_eligibility(posting, sid)
    return JobPosting(
        id=str(uuid4()),
        title=title,
        company=company,
        url=url,
        location=location,
        requirements=list({r.id: r for r in requirements}.values()),
        eligibility_requirements=eligibility_requirements,
        sources=[source],
    )
