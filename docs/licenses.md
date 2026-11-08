# Licences of the document stack

The FormLens API is proprietary (see [LICENSE](../LICENSE)). The models and libraries below keep
their own licences. This page records what they are, which versions the project was tried with and
how each statement was checked.

**Last checked: 2026-11-08.** The check was automated (the Hugging Face API for the model
metadata, the installed package metadata for the libraries). It is not a legal review, and nobody
has read the licence texts or the pages linked below yet: see [Open checks](#open-checks).

## Models

Both models are IBM's Granite-Docling-258M, the same model in two formats. The service downloads one
of them, chosen by `VLM_BACKEND`, with `make download-models`. The revisions are pinned in
`scripts/download_models.sh`; `tests/test_docs.py` fails when this table and the script disagree.

| `VLM_BACKEND` | Repository | Pinned revision | Licence | Status |
| --- | --- | --- | --- | --- |
| `mlx` | [ibm-granite/granite-docling-258M-mlx](https://huggingface.co/ibm-granite/granite-docling-258M-mlx) | `e9939db25d2f296c8678d0491c4609a8c596c50a` | Apache-2.0 | Metadata read from the Hugging Face API at that revision (`license: apache-2.0`, not gated); model card not read |
| `transformers` | [ibm-granite/granite-docling-258M](https://huggingface.co/ibm-granite/granite-docling-258M) | `982fe3b40f2fa73c365bdb1bcacf6c81b7184bfe` | Apache-2.0 | Metadata read from the Hugging Face API at that revision (`license: apache-2.0`, not gated); model card not read |

The `mlx` repository lists `ibm-granite/granite-docling-258M` as its base model. Only the `mlx`
model has been run (Stage 0 launch test, see below).

## Libraries

Docling and its VLM dependencies are **not** in `pyproject.toml` or `uv.lock` yet (Stage 0 ships no
parsing code). The versions below are those a scratch environment resolved on 2026-11-08 for
`docling[vlm]` on Python 3.15.2, macOS arm64, and that `uv add 'docling[vlm]'` also resolved against
this project's `requires-python`. Stage 1 locks them and updates this table.

| Package | Version tried | Licence declared in the package metadata | Status |
| --- | --- | --- | --- |
| [docling](https://github.com/docling-project/docling) | 2.149.0 | MIT | Metadata only; licence file not read |
| docling-core | 2.106.0 | MIT | Metadata only |
| docling-ibm-models | 4.0.4 | MIT | Metadata only |
| docling-parse | 7.24.2 | MIT | Metadata only |
| [mlx](https://github.com/ml-explore/mlx) | 0.32.4 | MIT | **Unverified**: metadata only, PyPI page and licence file not read |
| [mlx-vlm](https://pypi.org/project/mlx-vlm/) | 0.7.12 | MIT | **Unverified**: metadata only; its homepage field points to `neywalabs.ai`, not to a repository, so check who publishes it |
| [torch](https://pytorch.org) | 2.15.0 | Apache-2.0 AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND ISC AND MIT AND Zlib (and others, as declared) | **Unverified**: metadata only |
| [transformers](https://github.com/huggingface/transformers) | 5.22.2 | Apache-2.0 | **Unverified**: metadata only |
| huggingface-hub | 1.33.0 | Apache-2.0 | Metadata only |

`make download-models` runs `huggingface_hub` 2.4.0 through `uvx` (a separate, pinned tool
environment), which is not the 1.33.0 that Docling pulls in.

## What was run

Stage 0 launch test, in a scratch environment outside the repository: Python 3.15.2 on an Apple
Silicon Mac, `docling[vlm]` 2.149.0, the pinned `mlx` model from a local folder with
`HF_HUB_OFFLINE=1`, one synthetic page (a heading, a sentence and a three-row table drawn as
lines) through `VlmPipeline` with `GRANITEDOCLING_MLX`. The status was `SUCCESS` and the text came
back; the table was read as separate text cells, not as a table. This shows that the stack starts,
not that it extracts forms well.

## Open checks

Nobody has done these yet:

- Read both model cards and the Apache-2.0 text for the pinned revisions, and confirm no use
  restriction applies to this service.
- Read the licence of every library marked **Unverified**, and of the transitive dependencies
  that ship weights or data.
- Confirm that proprietary distribution of the service is compatible with all of the above.
- Repeat the check, and update the date at the top, whenever a revision or a package version
  changes.

## Sources

- Hugging Face model API: `https://huggingface.co/api/models/<repository>/revision/<revision>`
- Package metadata: `importlib.metadata.metadata("<package>")` in the scratch environment
- Docling: <https://github.com/docling-project/docling>
- Granite-Docling: <https://huggingface.co/ibm-granite/granite-docling-258M>
