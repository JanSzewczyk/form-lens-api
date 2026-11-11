# Run the language model

The extraction reads the fields of a form with a language model on the same machine. The service talks to it
through Ollama's OpenAI-compatible endpoint; nothing is sent anywhere else, and `LLM_BASE_URL` is refused unless
it names this machine or its private network.

> **Not verified.** This was written on a machine without Ollama. The commands below are Ollama's usual ones and
> the request fields the adapter sends (`response_format` with `json_schema`, `reasoning_effort: "none"`, `seed`,
> `temperature: 0`, `stream: false`) come from memory, **not from a run and not from the current documentation**.
> The first real run decides. If a field is not accepted, the adapter answers `llm_unavailable` (a 4xx) or
> `invalid_output` (an answer that does not fit the schema); the service log has the HTTP status as `http_status`
> or the cause as `cause_type`, never the text.

## 1. Install Ollama and pull the model

Install Ollama from <https://ollama.com>, start it (`ollama serve`, or the desktop app), then:

```bash
ollama pull qwen3:8b
ollama show qwen3:8b      # note the digest; put it in docs/licenses.md with the date
```

`LLM_MODEL` (default `qwen3:8b`) names the model; `LLM_BASE_URL` (default `http://localhost:11434/v1`) the
endpoint. Anything else is a setting change, not a code change.

## 2. Check that it answers

```bash
make evaluate
```

It checks first that Ollama answers at `LLM_BASE_URL` and lists `LLM_MODEL`, and stops with what to do when it does
not. It also needs the document model (`make download-models`). The full run reads 48 synthetic documents and
prints the exact-match and null-precision numbers; put them in the README's Accuracy section.

`make test-models` runs the `slow` tests, which include one extraction through the real document model and the
real Ollama.

## 3. Run the service

```bash
make migrate
make run
```

An extraction submitted while Ollama is down is retried once (`JOB_MAX_ATTEMPTS`) and then fails with
`llm_unavailable`.

## In Docker

Ollama runs on the host, not in the container. `compose.yaml` and `make docker-run` set
`LLM_BASE_URL=http://host.docker.internal:11434/v1` and map `host.docker.internal` to the host gateway, which Docker
Desktop already knows and Linux needs. Ollama must listen on an address the container can reach (on Linux that is
usually not the default loopback; check `OLLAMA_HOST`). This was **not run** either.

## If the model ignores the context size

A document longer than the model's context is cut or answered badly. `LLM_MAX_INPUT_CHARS` (default 20000) makes
the service refuse a longer text as `document_too_long` instead. If Ollama's `/v1` endpoint does not honour a
context size you set, make a derived model with a `Modelfile` and name it in `LLM_MODEL`:

```text
FROM qwen3:8b
PARAMETER num_ctx 16384
PARAMETER temperature 0
```

```bash
ollama create qwen3-8b-formlens -f Modelfile
LLM_MODEL=qwen3-8b-formlens make run
```

No Modelfile is committed: whether it is needed depends on a run nobody has done.

## Choosing another model

The golden set decides. Change `LLM_MODEL`, run `make evaluate`, compare the numbers. The parsed texts are cached
in `.golden/`, so the document model does not run again. A new default must also be written in
[licenses](../licenses.md) (a test checks that the page names it), with its licence read by a person.
