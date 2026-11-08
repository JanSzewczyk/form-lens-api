# Remove the example domain

The example (books and loans) lives in one package and one test folder, and `main.py` mounts it
with one line. Nothing outside `library/` imports it except `main.py`, and an import contract
enforces that (`make imports`).

<!-- begin:template -->
## The quick way

```bash
python scripts/init_project.py <your-name> --without-example
uv sync && make openapi && make check
```

<!-- end:template -->
## By hand

Replace `fastapi_szumplate` with your package name.

1. Delete `src/fastapi_szumplate/library/` and `tests/library/`.
2. In `src/fastapi_szumplate/main.py` delete the import of `include_library` and the call
   `include_library(app)`.
3. In `src/fastapi_szumplate/config.py` delete `loans_max_active_per_member` and `loan_days`; in
   `.env.example` delete `LOANS_MAX_ACTIVE_PER_MEMBER` and `LOAN_DAYS`. Keep `default_page_size`;
   `pagination.py` uses it.
4. In `pyproject.toml`, under `[tool.importlinter]`, delete every contract that mentions
   `.library`. Keep the core contracts ("The core is layered: …" and "Only the entry point
   imports the web server"): they guard the core, and import-linter fails without contracts.
5. Regenerate the spec and run the checks:

   ```bash
   make openapi
   make check
   ```

What stays: health endpoints, settings, logging, request-id middleware, Problem Details, OpenAPI
tooling, pagination and the `types.py` helpers, each with its own tests.

`factory-boy` and `hypothesis` stay in the `test` group; remove them with
`uv remove --group test factory-boy hypothesis` if your tests do not use them.

<!-- begin:template -->
## Check it

`template-smoke` in `.github/workflows/ci.yml` (locally `make smoke-template`) does exactly this
on a copy of the template and fails if `make check` is not green afterwards.
<!-- end:template -->
