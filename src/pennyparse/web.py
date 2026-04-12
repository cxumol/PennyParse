from .config import PENNYPARSE_HOST, PENNYPARSE_PORT
import uvicorn

import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
app = FastAPI()

PANDOC_CONTENT_TYPES = {
    "application/epub+zip": "epub",
    "application/rtf": "rtf",
    "application/vnd.oasis.opendocument.text": "odt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/html": "html",
    "text/markdown": "markdown",
    "text/plain": "markdown",
}
PANDOC_SUFFIXES = {
    "docx": ".docx",
    "epub": ".epub",
    "html": ".html",
    "markdown": ".md",
    "odt": ".odt",
    "rtf": ".rtf",
}


def _pdf_text(document) -> str:
    return chr(12).join(page.get_text() for page in document)


def _pdf_metadata(document) -> dict[str, int | list[list[int | str]]]:
    return {
        "pageCount": document.page_count,
        "wordCount": sum(len(page.get_text("words")) for page in document),
        "TOC": document.get_toc(),
    }


def _request_content_type(request: Request) -> str:
    return request.headers.get("content-type", "").split(";", 1)[0].strip().lower()


def _not_implemented() -> HTTPException:
    return HTTPException(status_code=501, detail="Not Implemented. If you're working on programatic integrations, skip this tool.")


async def _open_pdf_request(request: Request, pymupdf):
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="send a PDF request body")

    content_type = _request_content_type(request)
    if content_type and content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="request body must be a PDF")

    try:
        return pymupdf.open(stream=body, filetype="pdf")
    except (pymupdf.EmptyFileError, pymupdf.FileDataError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="invalid PDF payload") from exc


def _pandoc_format(request: Request, fmt: str | None) -> str:
    if fmt:
        return fmt.strip().lower()
    inferred = PANDOC_CONTENT_TYPES.get(_request_content_type(request))
    if inferred:
        return inferred
    raise HTTPException(status_code=400, detail="provide fmt or a supported content-type")


@app.post("/extraparser/pdf2txt", response_class=PlainTextResponse)
async def pdf2txt(request: Request) -> str:
    """Extract text from a raw PDF request body."""
    try:
        import pymupdf
    except ImportError as exc:
        raise _not_implemented() from exc

    with await _open_pdf_request(request, pymupdf) as document:
        return _pdf_text(document)


@app.post("/extraparser/pdf_metadata")
async def pdf_metadata(request: Request) -> dict[str, int | list[list[int | str]]]:
    """Extract metadata from a raw PDF request body."""
    try:
        import pymupdf
    except ImportError as exc:
        raise _not_implemented() from exc

    with await _open_pdf_request(request, pymupdf) as document:
        return _pdf_metadata(document)


@app.post("/extraparser/pandoc2txt", response_class=PlainTextResponse)
async def pandoc2txt(request: Request, fmt: str | None = None) -> str:
    """Extract text from a raw document body with pandoc."""
    try:
        import pypandoc
    except ImportError as exc:
        raise _not_implemented() from exc

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="send a document request body")

    input_format = _pandoc_format(request, fmt)
    suffix = PANDOC_SUFFIXES.get(input_format, f".{input_format}")

    try:
        with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            Path(tmp.name).write_bytes(body)
            return pypandoc.convert_file(tmp.name, to="plain", format=input_format)
    except RuntimeError as exc:
        if "No pandoc was found" in str(exc):
            raise _not_implemented() from exc
        raise HTTPException(status_code=400, detail=f"pandoc failed to parse {input_format}") from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"invalid {input_format} payload") from exc


if __name__ == "__main__":
    uvicorn.run(app, host=PENNYPARSE_HOST,
                    port=PENNYPARSE_PORT)
