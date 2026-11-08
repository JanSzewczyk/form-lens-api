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
`scripts/download_models.sh`; `tests/test_docs.py` fails when this table and the script disagree.

| `VLM_BACKEND` | Repository | Pinned revision | Licence | Status |
| --- | --- | --- | --- | --- |
| `mlx` | [ibm-granite/granite-docling-258M-mlx](https://huggingface.co/ibm-granite/granite-docling-258M-mlx) | `e9939db25d2f296c8678d0491c4609a8c596c50a` | Apache-2.0 | Front matter `license: apache-2.0` compared at that revision; model card body not read |
| `transformers` | [ibm-granite/granite-docling-258M](https://huggingface.co/ibm-granite/granite-docling-258M) | `982fe3b40f2fa73c365bdb1bcacf6c81b7184bfe` | Apache-2.0 | Front matter `license: apache-2.0` compared at that revision; model card body not read |

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
| [mlx-vlm](https://pypi.org/project/mlx-vlm/) | 0.7.12 | MIT | **Unverified**: metadata only. PyPI `project_urls` give `Repository: https://github.com/Neywa-Labs/mlx-vlm` and `Homepage: https://www.neywalabs.ai`. Confirm who publishes it, and that it is the project meant, before Stage 1 adds it |
| [torch](https://pytorch.org) | 2.15.0 | Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND ISC AND MIT AND Zlib | **Unverified**: metadata only |
| [transformers](https://github.com/huggingface/transformers) | 5.22.2 | Apache-2.0 | **Unverified**: metadata only |
| huggingface-hub (Docling's environment) | 1.33.0 | Apache-2.0 | Metadata only |

### The downloader

`make download-models` runs `huggingface_hub` **2.4.0** (Apache-2.0 in its PyPI metadata) through
`uvx --from huggingface_hub==2.4.0 hf`. That is a tool environment of its own, separate from the
1.33.0 that Docling pulls in. It runs **outside `uv.lock`**:

- only `huggingface_hub` itself is pinned; its dependencies (`click`, `filelock`, `fsspec`,
  `hf-xet`, `httpx2`, `packaging`, `pyyaml`, `tqdm`, `typing-extensions`) resolve to whatever is
  newest when `uvx` builds the environment, with no hashes;
- `make audit` does not see them, because it audits the locked groups only;
- their licences are not recorded here.

Dependabot does not bump the pin either (it sits in `scripts/download_models.sh`). Bring the
downloader under the lock, or accept this gap, in Stage 1.

## What was run

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
- Confirm the publisher of `mlx-vlm` (see its row) before Stage 1 adds it.
- Decide whether the downloader's environment stays outside `uv.lock` (see
  [The downloader](#the-downloader)).
- Read the licence of every package marked **Unverified**, and of the transitive dependencies
  that ship weights or data.
- Confirm that proprietary distribution of the service is compatible with all of the above.
- Repeat the comparison, and update the date at the top, whenever a revision or a package version
  changes.

## Sources

- Model card front matter: `https://huggingface.co/<repository>/raw/<revision>/README.md`
- Package metadata: `https://pypi.org/pypi/<package>/<version>/json` (`info.license`,
  `info.license_expression`, `info.project_urls`, `info.requires_dist`)
- Docling: <https://github.com/docling-project/docling>
- Granite-Docling: <https://huggingface.co/ibm-granite/granite-docling-258M>
