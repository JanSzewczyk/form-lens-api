"""Reads the fields of a template with a local language model behind Ollama's OpenAI-compatible endpoint.

The answer is never trusted: it is validated against the template's JSON Schema, which is the contract, and a
result that does not satisfy it is an `InvalidOutput`. Nothing of the document, the prompt, a value or a
library's message is logged or put in an exception; the errors carry a word that names the cause.
"""

import json
import re
import string
import time
from importlib import resources
from typing import Any, Final

import httpx2
import structlog
from jsonschema import Draft202012Validator, FormatChecker, ValidationError, validators

from formlens.config import require_local_model_url
from formlens.extractions.domain.exceptions import InvalidOutput, LlmUnavailable
from formlens.extractions.domain.model import TemplateSnapshot
from formlens.patterns import UnsupportedPattern, matches

log = structlog.get_logger(__name__)

# Bumped with the prompt file; the golden set's numbers are tied to it.
PROMPT_VERSION: Final = "field_extraction.v1"
_PROMPT_FILE: Final = f"{PROMPT_VERSION}.md"
SEED: Final = 7
OPEN_MARK: Final = "<<<DOCUMENT>>>"
CLOSE_MARK: Final = "<<<END OF DOCUMENT>>>"
_THINK_BLOCK: Final = re.compile(r"^\s*<think>.*?</think>\s*", re.DOTALL)


def _pattern_keyword(validator: Any, pattern: str, instance: Any, _schema: Any) -> Any:
    """JSON Schema `pattern` in the linear-time engine: a pattern from a client cannot make a job hang."""
    if validator.is_type(instance, "string") and not matches(pattern, instance):
        yield ValidationError("does not match the pattern")


_Validator = validators.extend(  # type: ignore[no-untyped-call]  # jsonschema does not type `extend`
    Draft202012Validator, {"pattern": _pattern_keyword}
)


def _load_prompt() -> string.Template:
    text = resources.files("formlens.extractions.adapters").joinpath("prompts", _PROMPT_FILE).read_text("utf-8")
    return string.Template(text)


def _neutralise(text: str) -> str:
    """Make the markers that frame the document impossible to write inside it."""
    return text.replace("<<<", "< < <").replace(">>>", "> > >")


def build_prompt(text: str, template: TemplateSnapshot) -> str:
    """Return the instruction for the model, the document framed between two markers.

    `string.Template` substitutes values and never evaluates them, so a `$` or a `{}` in the document or in a
    field description is only text.
    """
    fields = "\n".join(
        f"- {item.name} ({item.type}){': ' + item.description if item.description else ''}" for item in template.fields
    )
    return _load_prompt().substitute(
        form_name=template.name, field_list=fields, open=OPEN_MARK, close=CLOSE_MARK, document=_neutralise(text)
    )


class OllamaFieldExtractor:
    """Asks the model for the fields of a template and validates what comes back."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        """Build the client. The URL must be a local model server, whoever built the client.

        `trust_env=False`: the proxy variables of the environment are not read, so a document cannot be routed
        through a proxy that was set for something else.
        """
        require_local_model_url(base_url)
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._model = model
        self._client = httpx2.Client(timeout=httpx2.Timeout(timeout_seconds), trust_env=False, transport=transport)

    def close(self) -> None:
        """Close the connections."""
        self._client.close()

    def extract(self, text: str, template: TemplateSnapshot) -> dict[str, Any]:
        """Return one value per field, `None` where the text has none.

        Raises:
            LlmUnavailable: The model could not be reached, did not answer in time, or answered with an error status.
            InvalidOutput: The answer is not JSON, or does not satisfy the template's schema.
        """
        schema = {key: value for key, value in template.json_schema.items() if key != "$schema"}
        body = {
            "model": self._model,
            "messages": [{"role": "user", "content": build_prompt(text, template)}],
            "temperature": 0,
            "seed": SEED,
            "stream": False,
            "reasoning_effort": "none",  # no thinking: a reasoning model would spend the time budget on it
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "extraction", "strict": True, "schema": schema},
            },
        }
        started = time.perf_counter()
        try:
            response = self._client.post(self._url, json=body)
        except httpx2.TimeoutException:
            raise LlmUnavailable("timeout") from None
        except httpx2.HTTPError as exc:
            raise LlmUnavailable(type(exc).__name__) from None
        if response.status_code >= httpx2.codes.BAD_REQUEST:
            raise LlmUnavailable(f"http_{response.status_code}")
        result = self._read(response, template)
        log.info(
            "llm_answered",
            model=self._model,
            instruction_version=PROMPT_VERSION,
            http_status=response.status_code,
            elapsed_ms=round((time.perf_counter() - started) * 1000),
            input_chars=len(text),
        )
        return result

    @staticmethod
    def _read(response: httpx2.Response, template: TemplateSnapshot) -> dict[str, Any]:
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except ValueError, KeyError, IndexError, TypeError:
            raise InvalidOutput("no_content") from None
        if not isinstance(content, str):
            raise InvalidOutput("no_content")
        try:
            result = json.loads(_THINK_BLOCK.sub("", content))
        except ValueError:
            raise InvalidOutput("not_json") from None
        if not isinstance(result, dict):
            raise InvalidOutput("not_an_object")
        try:
            invalid = next(
                iter(
                    _Validator(template.json_schema, format_checker=FormatChecker()).iter_errors(result),
                ),
                None,
            )
        except UnsupportedPattern:
            raise InvalidOutput("pattern") from None
        if invalid is not None:
            raise InvalidOutput("schema")
        return result
