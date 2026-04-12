# Extraparser Endpoints

`POST /extraparser/pdf2txt`

- Send raw PDF bytes in the request body.
- Accepts `Content-Type: application/pdf` or `application/octet-stream`.
- Returns extracted plain text.

```sh
curl -X POST -H 'Content-Type: application/pdf' --data-binary @sample.pdf "${PENNYPARSE_BASE}/extraparser/pdf2txt"
```

`POST /extraparser/pdfmetadata`

- Send raw PDF bytes in the request body.
- Accepts `Content-Type: application/pdf` or `application/octet-stream`.
- Returns JSON with `pageCount`, `wordCount`, and `TOC`.

```sh
curl -X POST -H 'Content-Type: application/pdf' --data-binary @sample.pdf "${PENNYPARSE_BASE}/extraparser/pdfmetadata"
```

`POST /extraparser/pandoc2txt`

- Send raw document bytes in the request body.
- Set query parameter `fmt` to the pandoc input format, for example `docx`, `odt`, `rtf`, `html`, `markdown`, `epub`.
- If `fmt` is omitted, the server tries to infer it from `Content-Type`.
- Returns pandoc's plain-text output.

```sh
curl -X POST -H 'Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document' --data-binary @sample.docx "${PENNYPARSE_BASE}/extraparser/pandoc2txt?fmt=docx"
```
