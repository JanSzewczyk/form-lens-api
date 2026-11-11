# Licences of the document stack

The FormLens API is proprietary (see [LICENSE](../LICENSE)). The models and libraries below keep
their own licences. This page records what they are, which versions the project was tried with and
how each statement was checked.

**Last compared: 2026-11-08, by a script. No person has read any of it.** The comparison covered:

- the front matter of the model card (`license: apache-2.0`), fetched as the raw `README.md` of each
  repository at its pinned revision;
- the licence fields of the PyPI metadata of each package at the version named below, and the
  `project_urls` of `mlx-vlm`.

It did **not** cover the body of either model card, the Apache-2.0 text, any use restriction in a
model card or a package, or the licence files inside the packages. It is not a legal review. The
reading is a step for a person: see [Open checks](#open-checks).

## Models

Both models are IBM's Granite-Docling-258M, the same model in two formats. The service downloads one
of them, chosen by `VLM_BACKEND`, with `make download-models`. The revisions are pinned in
`src/formlens/modelspec.py`; `tests/test_docs.py` fails when this table and that file disagree.

| `VLM_BACKEND` | Repository | Pinned revision | Licence | Status |
| --- | --- | --- | --- | --- |
| `mlx` | [ibm-granite/granite-docling-258M-mlx](https://huggingface.co/ibm-granite/granite-docling-258M-mlx) | `e9939db25d2f296c8678d0491c4609a8c596c50a` | Apache-2.0 | Front matter `license: apache-2.0` compared at that revision; model card body not read |
| `transformers` | [ibm-granite/granite-docling-258M](https://huggingface.co/ibm-granite/granite-docling-258M) | `982fe3b40f2fa73c365bdb1bcacf6c81b7184bfe` | Apache-2.0 | Front matter `license: apache-2.0` compared at that revision; model card body not read |

The `mlx` repository lists `ibm-granite/granite-docling-258M` as its base model. Only the `mlx`
model has been run: the Stage 0 launch test and, in Stage 1, the real-model tests and the timing
measurement (see below).

## Libraries

Docling (`docling[vlm]`) and `python-multipart` are runtime dependencies in `pyproject.toml`, and
`uv.lock` records the versions below, which Stage 1 locked and ran on Python 3.15.2, macOS arm64
(2026-11-08). `docling` itself is a thin package: the code lives in `docling-slim`
(MIT), which it pulls in with the `standard` and `models-vlm-inline` extras.

| Package | Version tried | Licence declared in the package metadata | Status |
| --- | --- | --- | --- |
| [docling](https://github.com/docling-project/docling) | 2.149.0 | MIT | Metadata only; licence file not read |
| docling-slim | 2.149.0 | MIT | Metadata only; the package that holds Docling's code |
| docling-core | 2.106.0 | MIT | Metadata only |
| docling-ibm-models | 4.0.4 | MIT | Metadata only |
| docling-parse | 7.24.2 | MIT | Metadata only |
| [mlx](https://github.com/ml-explore/mlx) | 0.32.4 | MIT | **Unverified**: metadata only, PyPI page and licence file not read |
| [mlx-vlm](https://pypi.org/project/mlx-vlm/) | 0.7.12 | MIT | **Unverified**: metadata only. PyPI `project_urls` give `Repository: https://github.com/Neywa-Labs/mlx-vlm` and `Homepage: https://www.neywalabs.ai`. It is locked and runs in production code paths (Docling's `vlm` extra pulls it in on macOS arm64, and the `mlx` backend imports it), but **nobody has confirmed who publishes it or that it is the project meant. This check is still open** |
| [torch](https://pytorch.org) | 2.15.0 | Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND ISC AND MIT AND Zlib | **Unverified**: metadata only. On Linux the lock uses the CPU build `2.15.0+cpu` from the PyTorch index, so no `nvidia-*`, `cuda-toolkit` or `triton` package is locked (see [architecture](explanation/architecture.md#open-issues)); the licence of that build was not compared separately |
| [transformers](https://github.com/huggingface/transformers) | 5.22.2 | Apache-2.0 | **Unverified**: metadata only |
| [python-multipart](https://github.com/Kludex/python-multipart) | 0.0.33 | Apache-2.0 | Metadata only; a runtime dependency, FastAPI needs it to read an upload |
| huggingface-hub (Docling's environment) | 1.33.0 | Apache-2.0 | Metadata only |

The locked versions above were read from `uv.lock` on 2026-11-08; the licence column still comes from
the earlier metadata comparison and was not repeated for them.

### The downloader

`make download-models` runs `huggingface_hub` **2.4.0** (Apache-2.0 in its PyPI metadata) through
`uvx --from huggingface_hub==2.4.0 hf`. That is a tool environment of its own, separate from the
1.33.0 that Docling pulls in. It runs **outside `uv.lock`**:

- only `huggingface_hub` itself is pinned; its dependencies (`click`, `filelock`, `fsspec`,
  `hf-xet`, `httpx2`, `packaging`, `pyyaml`, `tqdm`, `typing-extensions`) resolve to whatever is
  newest when `uvx` builds the environment, with no hashes;
- `make audit` does not see them, because it audits the locked groups only;
- their licences are not recorded here.

Dependabot does not bump the pin either (it sits in `scripts/download_models.sh`). The gap is
open: the downloader is not under the lock yet, and Stage 1 did not close it. Decide whether to
bring it under the lock or to accept the gap (see [Open checks](#open-checks)).

## Stage 2: the language model and the libraries it added

Stage 2 reads the text of a document with a language model that runs on the same machine, through
Ollama. Nothing of it was downloaded or run when this section was written.

### The language model

| Setting | Model | Digest | Licence | Checked |
| --- | --- | --- | --- | --- |
| `LLM_MODEL` default: `qwen3:8b` | `qwen3:8b` in the Ollama library | **not recorded** | **not verified** | **not verified: the model was not pulled on the machine that built this** |

- The default is a choice, not a finding: the golden set (`make evaluate`, [README](../README.md#accuracy))
  is what decides the model, and `LLM_MODEL` is a setting.
- Nobody has read the model card, the licence of the weights or any use restriction. **Do not rely on any licence
  for this model until a person has read it.** The digest is expected in the output of
  `ollama list` and in the `/api/tags` answer of a running Ollama. **Not verified: Ollama was not available when
  this was written**, so which command and field give it has to be checked. Record it here with the date, and the
  licence text from the model card, when that is done.
- `tests/test_docs.py` fails when this table stops naming the default `LLM_MODEL`, so a change of the default
  cannot go by without this page.

### The libraries

These became runtime dependencies in Stage 2 (`sqlalchemy`, `alembic`, `httpx2` and `jsonschema` were asked for;
the rest are what they pull in, plus `pydantic-core`, whose linear-time regular expression engine now checks
the patterns of clients). The versions are the ones in `uv.lock`. The licence column is what the installed
package declares, read by `scripts/package_licenses.py`, which prints these rows (2026-11-11):

```bash
uv run python scripts/package_licenses.py sqlalchemy alembic mako markupsafe httpx2 httpcore2 truststore \
    jsonschema jsonschema-specifications referencing rpds-py attrs pydantic-core
```

| Package | Version | Licence declared in the package metadata | Field read |
| --- | --- | --- | --- |
| sqlalchemy | 2.1.8 | MIT | License-Expression |
| alembic | 1.20.1 | MIT | License-Expression |
| mako | 1.4.3 | MIT | License-Expression |
| markupsafe | 3.0.4 | BSD-3-Clause | License-Expression |
| httpx2 | 2.16.0 | BSD-3-Clause | License-Expression |
| httpcore2 | 2.16.0 | BSD-3-Clause | License-Expression |
| truststore | 0.10.5 | MIT | License-Expression |
| jsonschema | 4.26.0 | MIT | License-Expression |
| jsonschema-specifications | 2025.9.1 | MIT | License-Expression |
| referencing | 0.37.0 | MIT | License-Expression |
| rpds-py | 2026.9.1 | MIT | License-Expression |
| attrs | 26.1.0 | MIT | License-Expression |
| pydantic-core | 2.50.4 | MIT | License-Expression |

This is the same kind of check as for the libraries above: **metadata only; no licence file was read**. It
covers the packages that were added or became runtime dependencies, not every transitive dependency of the
service. `tests/test_docs.py` compares this table with the installed metadata, so a version bump that changes
a licence fails there.

## What was run

Stage 1: the real adapter with the pinned `mlx` model on an Apple M1 Pro, through `make test-models`:
a PDF with a text layer, a PDF scan and a PNG, each of one synthetic page (`tests/data/`), came back
as text with the page count, and an offline run with every network call blocked and recorded made no
attempt. The measured page time is in the README. The `transformers` model was not downloaded or run.

Stage 0 launch test, in a scratch environment outside the repository: Python 3.15.2 on an Apple
Silicon Mac, `docling[vlm]` 2.149.0, the pinned `mlx` model from a local folder with
`HF_HUB_OFFLINE=1`, one synthetic page (a heading, a sentence and a three-row table drawn as
lines) through `VlmPipeline` with `GRANITEDOCLING_MLX`. The status was `SUCCESS` and the text came
back; the table was read as separate text cells, not as a table. This shows that the stack starts,
not that it extracts forms well.

## Open checks

Nobody has done these yet; they are for a person, not a script:

- Read both model cards (not only the front matter) and the Apache-2.0 text for the pinned
  revisions, and confirm no use restriction applies to this service.
- Confirm the publisher of `mlx-vlm` (see its row); it is in `uv.lock` and the `mlx` backend runs
  it. **This stays open until a person has done it.**
- Decide whether the downloader's environment stays outside `uv.lock` (see
  [The downloader](#the-downloader)).
- Read the licence of every package marked **Unverified**, and of the transitive dependencies
  that ship weights or data.
- Confirm that proprietary distribution of the service is compatible with all of the above.
- Read the model card and the licence of the language model, record its digest, and replace the
  **not verified** cells of [The language model](#the-language-model).
- Repeat the comparison, and update the date at the top, whenever a revision or a package version
  changes.

## Sources

- Model card front matter: `https://huggingface.co/<repository>/raw/<revision>/README.md`
- Package metadata: `https://pypi.org/pypi/<package>/<version>/json` (`info.license`,
  `info.license_expression`, `info.project_urls`, `info.requires_dist`)
- Docling: <https://github.com/docling-project/docling>
- Granite-Docling: <https://huggingface.co/ibm-granite/granite-docling-258M>
