# Problem types

Every error body is `application/problem+json`. Branch on `type`; `title` is stable, `detail` is
for people. Types are `urn:problem:formlens:<slug>`.

| Slug | Status | Title | When |
| --- | --- | --- | --- |
| `validation-error` | 422 | Request validation failed | A body, path or query value is invalid on its own, or a query parameter that takes one value is given twice (`type` `repeated_parameter`). `errors` lists `loc`, `msg`, `type`; the submitted value is never returned. |
| `service-not-ready` | 503 | Service not ready | A readiness check failed. `detail` names the checks, not the errors. |

Errors the framework raises use `type` `about:blank` and the HTTP status phrase as `title`:

| Status | When |
| --- | --- |
| 400 | The body bytes are not decodable text (for example invalid UTF-8), or a CORS preflight was refused (`Disallowed CORS origin`, `method` or `headers`). |
| 404 | Unknown path. A trailing slash is not redirected; `/health/` is a 404. |
| 405 | Wrong method; the `Allow` header lists every method of the path. |
| 500 | Unhandled error. Fixed text, no exception details. |

Every response carries an `X-Request-ID` header, a 500 and a refused CORS preflight included. The
same value is in the body as `request_id` and in every log line of the request.
