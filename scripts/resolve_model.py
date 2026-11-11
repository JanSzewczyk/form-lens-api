"""Print which pinned model `make download-models` fetches, resolved the way the service resolves it.

It reads `MODELS_PATH` and `VLM_BACKEND` through `ModelSettings`: the environment first, then a
`.env` in the working directory, then the defaults. So a `.env` moves the download and the service
together, and a relative `MODELS_PATH` means the same folder to both.

On success it prints four lines to stdout and exits 0: the Hugging Face repository, the revision,
the folder name under the models path, and the models path. A setting the service would refuse is
reported on stderr and exits 3 (uv uses 1 and 2 for its own failures, Python uses 1 for a crash).

Usage: `python scripts/resolve_model.py`
"""

import argparse
import sys

from pydantic import ValidationError

from formlens.config import ModelSettings
from formlens.modelspec import MODEL_SPECS

REFUSED = 3


def refusals(error: ValidationError) -> list[str]:
    """Return one sentence per refused setting, in the wording of Stage 0: the backend first."""
    messages: list[str] = []
    for issue in error.errors():
        name = str(issue["loc"][0]) if issue["loc"] else ""
        if name == "vlm_backend":
            messages.append(f"VLM_BACKEND must be 'mlx' or 'transformers', not '{issue['input']}'.")
        elif name == "models_path" and issue["input"] == "":
            messages.append("MODELS_PATH must not be empty; unset it to use 'models'.")
        else:
            messages.append(f"{name.upper() or 'The settings'} is invalid: {issue['msg']}.")
    return sorted(messages, key=lambda message: not message.startswith("VLM_BACKEND"))


def main(argv: list[str] | None = None) -> int:
    """Print the model to download, or the reason the settings refuse, and return the exit code."""
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    try:
        settings = ModelSettings()
    except ValidationError as error:
        for message in refusals(error):
            print(message, file=sys.stderr)
        return REFUSED
    models_path = str(settings.models_path)
    if "\n" in models_path:
        print("MODELS_PATH must not contain a line break.", file=sys.stderr)
        return REFUSED
    spec = MODEL_SPECS[settings.vlm_backend]
    print(spec.repo, spec.revision, spec.folder, models_path, sep="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
