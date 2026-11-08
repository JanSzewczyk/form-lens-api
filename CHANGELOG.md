# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Settings `MODELS_PATH`, `VLM_BACKEND` (`mlx` or `transformers`), `MAX_UPLOAD_MB` and `MAX_CONCURRENCY`.
  An empty `MODELS_PATH` is refused, by the settings and by the download script.
- Setting `PARSE_TIMEOUT_SECONDS` (default 300): how long one document may take to parse.
- `make download-models` and `scripts/download_models.sh`: download the pinned Granite-Docling
  revision for the chosen backend into `MODELS_PATH`; running it again downloads nothing.
- `make test-models` and the `slow` test marker (deselected by default): fail unless the pinned
  model files are present.
- `docs/licenses.md`: licences, pinned revisions and open checks for the models and libraries.
- Architecture notes: the FormLens components, the Stage 0 decisions and the carry-forward notes
  for Stage 1.

### Changed

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
