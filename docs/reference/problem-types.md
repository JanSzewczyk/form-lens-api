# Problem types

Every error body is `application/problem+json`. Branch on `type`; `title` is stable, `detail` is
for people. Types are `urn:problem:formlens:<slug>`.

| Slug | Status | Title | When |
| --- | --- | --- | --- |
| `validation-error` | 422 | Request validation failed | A body, path or query value is invalid on its own, a query parameter that takes one value is given twice, or `POST /v1/documents/parse` gets two `file` parts (`type` `repeated_parameter`). A `file` part without a `filename` is refused here too: it is a text field, not an upload. `errors` lists `loc`, `msg`, `type`; the submitted value is never returned. |
| `service-not-ready` | 503 | Service not ready | A readiness check failed. `detail` names the checks, not the errors. |
| `invalid-file` | 400 | Invalid file | `POST /v1/documents/parse`: the file is empty, or it has a PDF, PNG, JPEG or TIFF signature but the model cannot read it (a corrupt file, an image with absurd dimensions). |
| `file-too-large` | 413 | File too large | The upload is larger than `MAX_UPLOAD_MB`. A body that is far larger is refused before it is read. |
| `unsupported-media-type` | 415 | Unsupported media type | The file is not a PDF, PNG, JPEG or TIFF. The type is read from the bytes; the client's `Content-Type` and file name are ignored. |
| `parse-failed` | 500 | Document could not be parsed | The model failed, ran past `PARSE_TIMEOUT_SECONDS`, or returned an incomplete result. An incomplete text is never returned. |
| `model-unavailable` | 503 | Model unavailable | The document model is not loaded. |
| `parser-busy` | 503 | Parser busy | Every parsing slot (`MAX_CONCURRENCY`) is taken. The `Retry-After` header says how many seconds to wait. Nothing is queued. |
| `template-not-found` | 404 | Template not found | `GET`, `PUT` or `DELETE /v1/templates/{template_id}`: no template has this id. |
| `invalid-template` | 422 | Invalid template | `POST /v1/templates` or `PUT /v1/templates/{template_id}`: the body is well formed but the template breaks a rule. `detail` names the field and the rule, never a value the client sent. The rules: 1 to 50 fields with unique names of `a-z`, `0-9` and `_` (starting with a letter, at most 64 characters); a `choice` has 1 to 50 distinct `allowed_values` and no other type has any; `minimum` and `maximum` are finite, only for `number` and `integer`, and not in the wrong order; `pattern` is only for `text`, at most 200 characters and a valid regular expression; the name is 1 to 100 characters and the descriptions at most 300. |

Errors the framework raises use `type` `about:blank` and the HTTP status phrase as `title`:

| Status | When |
| --- | --- |
| 400 | The body bytes are not decodable text (for example invalid UTF-8), a multipart body is malformed (`Invalid multipart data.`, `Missing boundary in multipart.`), or a CORS preflight was refused (`Disallowed CORS origin`, `method` or `headers`). |
| 404 | Unknown path. A trailing slash is not redirected; `/health/` is a 404. |
| 405 | Wrong method; the `Allow` header lists every method of the path. |
| 500 | Unhandled error. Fixed text, no exception details. |

Every response carries an `X-Request-ID` header, a 500 and a refused CORS preflight included. The
same value is in the body as `request_id` and in every log line of the request.
