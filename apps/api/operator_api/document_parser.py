"""Binary document text extraction for PDF and DOCX resume uploads.

Both parsers work entirely in-memory via io.BytesIO.
No temp files are created; no network calls are made.
Raises ValueError with a user-safe message when extraction fails or
the extracted text is empty.
"""

from __future__ import annotations

import io

_MAX_PDF_PAGES = 200  # guard against enormous documents
_MAX_TEXT_LEN = 200_000  # characters; truncated, not rejected


def extract_pdf(data: bytes) -> str:
    """Return plain text from a PDF byte string.

    Joins all pages with newlines.  Raises ValueError when the PDF cannot
    be parsed, is encrypted without a known password, or yields no text.
    """
    try:
        import pypdf  # noqa: PLC0415
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError("pypdf is not installed") from exc

    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise ValueError(f"Could not read PDF: {exc}") from exc

    if reader.is_encrypted:
        raise ValueError("Encrypted PDFs are not supported. Save an unencrypted copy and try again.")

    pages = reader.pages[: _MAX_PDF_PAGES]
    parts: list[str] = []
    for page in pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        parts.append(text)

    result = "\n".join(parts).strip()
    if not result:
        raise ValueError(
            "No text could be extracted from the PDF. "
            "If the file is scanned or image-only, paste the text manually instead."
        )
    return result[:_MAX_TEXT_LEN]


def extract_docx(data: bytes) -> str:
    """Return plain text from a DOCX byte string.

    Joins all paragraph texts with newlines.  Raises ValueError when the
    DOCX cannot be parsed or yields no text.
    """
    try:
        import docx  # noqa: PLC0415
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError("python-docx is not installed") from exc

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise ValueError(f"Could not read DOCX: {exc}") from exc

    parts = [para.text for para in document.paragraphs if para.text.strip()]
    result = "\n".join(parts).strip()
    if not result:
        raise ValueError(
            "No text could be extracted from the DOCX. "
            "Try saving as plain text and using the text-paste form instead."
        )
    return result[:_MAX_TEXT_LEN]


# Magic-byte signatures for format sniffing (used before trusting the extension).
_PDF_MAGIC = b"%PDF"
_DOCX_MAGIC = b"PK\x03\x04"


def detect_format(filename: str, data: bytes) -> str | None:
    """Return 'pdf', 'docx', or None when the format is unrecognised.

    Checks the file extension first; falls back to magic-byte sniffing so
    mis-named files are caught before extraction is attempted.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "pdf" or data[:4] == _PDF_MAGIC:
        return "pdf"
    if ext == "docx" or data[:4] == _DOCX_MAGIC:
        return "docx"
    return None
