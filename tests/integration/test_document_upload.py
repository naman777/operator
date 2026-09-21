"""Integration tests for PDF and DOCX resume upload ingestion.

All PDF and DOCX objects are built in-memory so the tests do not
require any external files.
"""

from __future__ import annotations

import io

from fastapi.testclient import TestClient
from operator_api.main import create_app


# ---------------------------------------------------------------------------
# In-memory PDF builder (no external deps — uses pypdf's writer API)
# ---------------------------------------------------------------------------


def _make_pdf(text: str) -> bytes:
    """Return a minimal valid PDF containing *text*, one PDF text-row per input line.

    Each line is placed using a separate Td operator so pypdf's extract_text()
    returns them separated by newlines — which the heuristic resume parser needs
    to locate section headers.
    """
    import pypdf
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    lines = text.split("\n")
    # Build content stream: move down 15 pts per line.
    ops = ["BT", "/F1 12 Tf", "50 700 Td"]
    for i, line in enumerate(lines):
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").replace("\r", "")
        if i == 0:
            ops.append(f"({safe}) Tj")
        else:
            ops.append(f"0 -15 Td ({safe}) Tj")
    ops.append("ET")
    content = "\n".join(ops)

    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    writer.add_page(page)

    stream = DecodedStreamObject()
    stream.set_data(content.encode("latin-1", errors="replace"))
    page[NameObject("/Contents")] = writer._add_object(stream)

    font_dict = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
            NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
        }
    )
    font_ref = writer._add_object(font_dict)
    resources = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    page[NameObject("/Resources")] = resources

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()



# ---------------------------------------------------------------------------
# In-memory DOCX builder
# ---------------------------------------------------------------------------


def _make_docx(text: str) -> bytes:
    """Return a minimal valid DOCX containing *text* in a single paragraph."""
    import docx

    doc = docx.Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _app(tmp_path):
    return create_app(f"sqlite:///{tmp_path / 'upload.db'}")


def _guest(client):
    return {"Authorization": "Bearer " + client.post("/v1/guest-sessions?demo=true").json()["token"]}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_pdf_upload_extracts_text_and_creates_evidence(tmp_path):
    """A valid PDF upload should return 201 with evidence_count > 0."""
    with TestClient(_app(tmp_path)) as client:
        headers = _guest(client)
        pdf_bytes = _make_pdf("Python FastAPI developer with 3 years experience")
        resp = client.post(
            "/v1/profile/documents/upload",
            headers=headers,
            files={"file": ("resume.pdf", pdf_bytes, "application/pdf")},
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["evidence_count"] > 0
        assert data["document_id"]
        profile = client.get("/v1/profile", headers=headers).json()
        assert any(e["document_id"] == data["document_id"] for e in profile["evidence"])


def test_docx_upload_extracts_text_and_creates_evidence(tmp_path):
    """A valid DOCX upload should return 201 with evidence_count > 0."""
    with TestClient(_app(tmp_path)) as client:
        headers = _guest(client)
        docx_bytes = _make_docx("TypeScript React engineer, experience with Docker and SQL")
        resp = client.post(
            "/v1/profile/documents/upload",
            headers=headers,
            files={"file": ("resume.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["evidence_count"] > 0
        profile = client.get("/v1/profile", headers=headers).json()
        assert any(e["document_id"] == data["document_id"] for e in profile["evidence"])


def test_upload_rejects_oversized_file(tmp_path):
    """Files larger than 5 MB should return 413."""
    with TestClient(_app(tmp_path)) as client:
        headers = _guest(client)
        big = b"a" * (5 * 1024 * 1024 + 1)
        resp = client.post(
            "/v1/profile/documents/upload",
            headers=headers,
            files={"file": ("big.pdf", big, "application/pdf")},
        )
        assert resp.status_code == 413


def test_upload_rejects_unsupported_type(tmp_path):
    """A plain-text file sent to the upload endpoint should return 422."""
    with TestClient(_app(tmp_path)) as client:
        headers = _guest(client)
        resp = client.post(
            "/v1/profile/documents/upload",
            headers=headers,
            files={"file": ("resume.txt", b"Some experience here.", "text/plain")},
        )
        assert resp.status_code == 422
        assert "Unsupported file type" in resp.json()["detail"]


def test_upload_deduplication(tmp_path):
    """Uploading the same file twice should return the same document_id."""
    with TestClient(_app(tmp_path)) as client:
        headers = _guest(client)
        docx_bytes = _make_docx("Duplicate test resume — Python developer")
        def upload():
            return client.post(
                "/v1/profile/documents/upload",
                headers=headers,
                files={"file": ("dup.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            ).json()

        first = upload()
        second = upload()
        assert first["document_id"] == second["document_id"]
        # Profile version must not increment on the duplicate.
        assert first["profile_version"] == second["profile_version"]


def test_pdf_upload_structural_parse(tmp_path):
    """A PDF whose text contains graduation year and date ranges should populate profile fields."""
    # Use newlines so the section-header regex in the heuristic parser can
    # isolate the education section (Class of 2023) from the experience section
    # (Jan 2023 – Dec 2024).  PDF text extraction preserves newlines from pages.
    resume_text = (
        "EDUCATION\n"
        "B.S. Computer Science, State University, Class of 2023\n"
        "\n"
        "WORK EXPERIENCE\n"
        "Software Engineer Acme Corp Jan 2023 to Dec 2024\n"
        "\n"
        "SKILLS\n"
        "Python Docker FastAPI"
    )

    with TestClient(_app(tmp_path)) as client:
        headers = _guest(client)
        pdf_bytes = _make_pdf(resume_text)
        resp = client.post(
            "/v1/profile/documents/upload",
            headers=headers,
            files={"file": ("resume.pdf", pdf_bytes, "application/pdf")},
        )
        assert resp.status_code == 201, resp.text
        profile = client.get("/v1/profile", headers=headers).json()
        # Graduation year extracted from "Class of 2023".
        assert profile["graduation_year"] == 2023
        # Experience years extracted from date range (any positive value).
        assert profile["experience_years"] is not None and profile["experience_years"] > 0


def test_upload_requires_auth(tmp_path):
    """Upload without a valid token should return 401."""
    with TestClient(_app(tmp_path)) as client:
        docx_bytes = _make_docx("No auth test")
        resp = client.post(
            "/v1/profile/documents/upload",
            files={"file": ("resume.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        assert resp.status_code == 401
