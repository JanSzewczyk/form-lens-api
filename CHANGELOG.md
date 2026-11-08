# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Settings `MODELS_PATH`, `VLM_BACKEND` (`mlx` or `transformers`), `MAX_UPLOAD_MB` and `MAX_CONCURRENCY`.
  An empty `MODELS_PATH` is refused, by the settings and by the download script.
- `make download-models` and `scripts/download_models.sh`: download the pinned Granite-Docling
  revision for the chosen backend into `MODELS_PATH`; running it again downloads nothing.
- `make test-models` and the `slow` test marker (deselected by default): fail unless the pinned
  model files are present.
- `docs/licenses.md`: licences, pinned revisions and open checks for the models and libraries.
- Architecture notes: the FormLens components, the Stage 0 decisions and the carry-forward notes
  for Stage 1.

### Changed

- The project is initialised from the template as `formlens` and has no example domain.
- The licence is proprietary (all rights reserved); the OpenAPI document, `LICENSE` and the
  package metadata say so.
- The OpenAPI description and contact URL describe FormLens.
