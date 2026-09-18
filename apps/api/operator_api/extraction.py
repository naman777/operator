"""Bounded HTTPS ingestion using a pinned public address and JSON-LD JobPosting data."""

import hashlib
from html.parser import HTMLParser
import http.client
import ipaddress
import json
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit
from uuid import uuid4
from .db import utcnow
from .schemas import JobPosting, Requirement, Source

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
    return JobPosting(
        id=str(uuid4()),
        title=title,
        company=company,
        url=url,
        location=location,
        requirements=list({r.id: r for r in requirements}.values()),
        sources=[source],
    )
