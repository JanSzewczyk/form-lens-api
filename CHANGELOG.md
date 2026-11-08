# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- `POST /v1/documents/parse`: upload a PDF, PNG, JPEG or TIFF (multipart `file`) and get `text`,
  `page_count`, `elapsed_ms` and `model`. `format=markdown` (default) or `format=text`. The type is
  read from the file's bytes. Errors are Problem Details: `invalid-file` (400), `file-too-large`
  (413), `unsupported-media-type` (415), `parse-failed` (500), `model-unavailable` (503) and
  `parser-busy` (503 with `Retry-After`).
- Docling with Granite-Docling (`docling[vlm]`) and `python-multipart` as runtime dependencies. The
  model is loaded once at start-up from `MODELS_PATH` with `HF_HUB_OFFLINE=1`; a missing model stops
  the start with a `model_load_failed` log line. Readiness has a `model` check.
- At most `MAX_CONCURRENCY` documents are parsed at once; the next request gets 503 at once.
- A body cap in front of the route refuses an oversized upload with 413 before it is read.
- `tests/schemathesis_app.py`: the app with a fake parser that `make schemathesis` fuzzes, started
  with `uvicorn --factory`.
- Slow tests with the real model, and an offline test that runs the service in a child process
  recording every network attempt (`make test-models` runs every `slow` test).
- The measured page time on an Apple M1 Pro is in the README.
- Settings `MODELS_PATH`, `VLM_BACKEND` (`mlx` or `transformers`), `MAX_UPLOAD_MB` and `MAX_CONCURRENCY`.
  An empty `MODELS_PATH` is refused, by the settings and by the download script.
- Setting `PARSE_TIMEOUT_SECONDS` (default 300): how long one document may take to parse.
- `make download-models` and `scripts/download_models.sh`: download the pinned Granite-Docling
  revision for the chosen backend into `MODELS_PATH`; running it again downloads nothing.
- `make test-models` and the `slow` test marker (deselected by default): fail unless the pinned
  model files are present.
- `docs/licenses.md`: licences, pinned revisions and open checks for the models and libraries.
- Architecture notes: the FormLens components, the decisions and the open issues.

### Changed

- `make test-models` runs every `slow` test (`pytest -m slow`), not only the model files check. The
  `slow` tests read `MODELS_PATH` and `VLM_BACKEND` from the environment and `.env` and no other
  setting.
- The image sets `VLM_BACKEND=transformers` and `MODELS_PATH=/models` and holds no model; `compose.yaml`
  and `make docker-run` mount the models read-only. The `docker` CI job checks that the image fails
  at start-up without a model, instead of waiting for it to become healthy.
- The `free-threaded` CI job is switched off: the locked dependencies have no free-threaded wheels.
- The readiness answer lists the `model` check.
- `make download-models` and `make test-models` now read `MODELS_PATH` and `VLM_BACKEND` as the
  service does: the environment first, then `.env`, then the defaults. Before, they read the
  environment only, so a `.env` moved the service but not the download. The pinned repositories
  and revisions moved from the script and `tests/model_pins.py` to `src/formlens/modelspec.py`,
  and the script needs the project environment (`make install`) to resolve them. An unrelated bad
  value in `.env` does not block a download.
- Log redaction also masks keys that could hold a document or its name (`filename`, `file_name`,
  `content`, `markdown`, `plain_text`, `extracted_text`). `content` is a substring match, so
  `content-type` and `content_length` are masked too.
- The loggers of Docling, Hugging Face, Pillow and MLX are held at `WARNING` (or at `LOG_LEVEL`
  when that is higher), so a file name or a model path they log at `INFO` never reaches the output.
- A domain error that carries `retry_after_seconds` answers with a `Retry-After` header, and a
  domain error with a status of 500 or more is logged at `ERROR`.
- The project is initialised from the template as `formlens` and has no example domain.
- The licence is proprietary (all rights reserved); the OpenAPI document, `LICENSE` and the
  package metadata say so.
- The OpenAPI description and contact URL describe FormLens.
