"""The Docling adapter, driven by a stub converter: no Docling import and no model."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import pytest

from formlens.config import Settings
from formlens.modelspec import MODEL_SPECS, VlmBackend
from formlens.parsing.docling_parser import DoclingParser, build_docling_parser, missing_model_files
from formlens.parsing.exceptions import InvalidFile, ModelUnavailable, ParseFailed
from tests.conftest import make_settings
from tests.documents import sample


@dataclass
class StubInput:
    valid: bool = True
    page_count: int = 2


@dataclass
class StubDocument:
    exported: list[str] = field(default_factory=list)

    def export_to_markdown(self) -> str:
        self.exported.append("markdown")
        return "# Markdown"

    def export_to_text(self) -> str:
        self.exported.append("text")
        return "Plain text"


@dataclass
class StubResult:
    status: str = "success"
    input: StubInput = field(default_factory=StubInput)
    document: StubDocument = field(default_factory=StubDocument)


@dataclass
class Call:
    name: str
    folder: Path
    content: bytes
    raises_on_error: bool
    max_file_size: int


class StubConverter:
    def __init__(self, result: StubResult | None = None, *, error: Exception | None = None) -> None:
        self.result = result or StubResult()
        self.error = error
        self.calls: list[Call] = []

    def convert(self, source: Path, *, raises_on_error: bool, max_file_size: int) -> StubResult:
        self.calls.append(Call(source.name, source.parent, source.read_bytes(), raises_on_error, max_file_size))
        if self.error is not None:
            raise self.error
        return self.result


def make_parser(converter: StubConverter, work_dir: Path | None = None, max_file_size: int = 1000) -> DoclingParser:
    return DoclingParser(converter, model_id="acme/model", max_file_size=max_file_size, work_dir=work_dir)


class TestParse:
    def test_a_successful_conversion_gives_both_texts_the_page_count_and_the_model(self, tmp_path: Path) -> None:
        parser = make_parser(StubConverter(), tmp_path)

        result = parser.parse(b"%PDF-1.4", "upload.pdf")

        assert (result.text, result.plain_text) == ("# Markdown", "Plain text")
        assert (result.page_count, result.model_id) == (2, "acme/model")
        assert result.elapsed_ms >= 0

    def test_the_converter_gets_the_bytes_under_the_neutral_name_and_is_told_not_to_raise(self, tmp_path: Path) -> None:
        converter = StubConverter()

        make_parser(converter, tmp_path, max_file_size=4321).parse(sample("sample.png"), "upload.png")

        [call] = converter.calls
        assert call.name == "upload.png"
        assert call.content == sample("sample.png")
        assert call.raises_on_error is False
        assert call.max_file_size == 4321
        assert call.folder.parent == tmp_path

    @pytest.mark.parametrize(
        ("name", "written_as"),
        [("../../etc/passwd.pdf", "passwd.pdf"), ("/abs/path/upload.pdf", "upload.pdf"), ("dir/scan.pdf", "scan.pdf")],
    )
    def test_a_name_with_a_path_in_it_never_leaves_the_temporary_folder(
        self, tmp_path: Path, name: str, written_as: str
    ) -> None:
        converter = StubConverter()

        make_parser(converter, tmp_path).parse(b"%PDF-", name)

        assert converter.calls[0].name == written_as
        assert converter.calls[0].folder.parent == tmp_path

    def test_an_empty_name_falls_back_to_a_neutral_one(self, tmp_path: Path) -> None:
        converter = StubConverter()

        make_parser(converter, tmp_path).parse(b"%PDF-", "")

        assert converter.calls[0].name == "upload"

    def test_the_temporary_folder_is_removed_after_a_success(self, tmp_path: Path) -> None:
        make_parser(StubConverter(), tmp_path).parse(b"%PDF-", "upload.pdf")

        assert list(tmp_path.iterdir()) == []

    def test_the_temporary_folder_is_removed_when_the_converter_raises(self, tmp_path: Path) -> None:
        parser = make_parser(StubConverter(error=RuntimeError("backend crashed")), tmp_path)

        with pytest.raises(ParseFailed):
            parser.parse(b"%PDF-", "upload.pdf")

        assert list(tmp_path.iterdir()) == []

    @pytest.mark.parametrize("status", ["failure", "partial_success", "skipped", "pending", "started"])
    def test_a_conversion_that_did_not_succeed_is_a_parse_failure_and_returns_no_text(
        self, tmp_path: Path, status: str
    ) -> None:
        result = StubResult(status=status)
        parser = make_parser(StubConverter(result), tmp_path)

        with pytest.raises(ParseFailed, match="could not be parsed") as failed:
            parser.parse(b"%PDF-", "upload.pdf")

        assert status in str(failed.value.__cause__)
        assert failed.value.conversion_status == status
        assert type(failed.value.__cause__).__name__ == "ConversionIncomplete"  # logged as `cause_type`: no `_`
        assert result.document.exported == []  # a partial text is never exported
        assert list(tmp_path.iterdir()) == []

    def test_a_timeout_is_a_partial_success_and_so_a_parse_failure(self, tmp_path: Path) -> None:
        """Docling answers an exceeded `document_timeout` with PARTIAL_SUCCESS, not an error."""
        parser = make_parser(StubConverter(StubResult(status="partial_success")), tmp_path)

        with pytest.raises(ParseFailed):
            parser.parse(b"%PDF-", "upload.pdf")

    def test_an_enum_status_is_reported_by_its_value(self, tmp_path: Path) -> None:
        class Status(Enum):
            PARTIAL_SUCCESS = "partial_success"

        parser = make_parser(StubConverter(StubResult(status=Status.PARTIAL_SUCCESS)), tmp_path)  # type: ignore[arg-type]

        with pytest.raises(ParseFailed) as failed:
            parser.parse(b"%PDF-", "upload.pdf")

        assert failed.value.conversion_status == "partial_success"

    def test_an_exception_has_no_conversion_status(self, tmp_path: Path) -> None:
        parser = make_parser(StubConverter(error=ValueError("x")), tmp_path)

        with pytest.raises(ParseFailed) as failed:
            parser.parse(b"%PDF-", "upload.pdf")

        assert failed.value.conversion_status is None

    def test_any_exception_of_docling_is_a_parse_failure_with_the_cause_kept_and_not_shown(
        self, tmp_path: Path
    ) -> None:
        cause = ValueError("text of the document: secret-marker-1138")
        parser = make_parser(StubConverter(error=cause), tmp_path)

        with pytest.raises(ParseFailed) as failed:
            parser.parse(b"%PDF-", "upload.pdf")

        assert failed.value.__cause__ is cause
        assert "secret-marker-1138" not in str(failed.value)

    def test_an_export_that_raises_is_a_parse_failure_too(self, tmp_path: Path) -> None:
        class Broken(StubDocument):
            def export_to_markdown(self) -> str:
                raise RuntimeError("export failed")

        parser = make_parser(StubConverter(StubResult(document=Broken())), tmp_path)

        with pytest.raises(ParseFailed):
            parser.parse(b"%PDF-", "upload.pdf")

    def test_an_input_docling_marks_invalid_is_an_invalid_file_not_a_failure(self, tmp_path: Path) -> None:
        """A PNG of absurd dimensions, a corrupt PDF: Docling sets `valid` to False and its status to failure."""
        result = StubResult(status="failure", input=StubInput(valid=False, page_count=0))
        parser = make_parser(StubConverter(result), tmp_path)

        with pytest.raises(InvalidFile, match="not a readable document"):
            parser.parse(b"\x89PNG\r\n\x1a\n", "upload.png")

        assert result.document.exported == []
        assert list(tmp_path.iterdir()) == []


def write_model(settings: Settings, *, skip: tuple[str, ...] = ()) -> Path:
    spec = MODEL_SPECS[settings.vlm_backend]
    folder = settings.models_path / spec.folder
    folder.mkdir(parents=True)
    for name in spec.files:
        if name not in skip:
            (folder / name).write_bytes(b"x")
    return folder


class TestMissingModelFiles:
    @pytest.mark.parametrize("backend", ["mlx", "transformers"])
    def test_a_complete_folder_misses_nothing(self, tmp_path: Path, backend: VlmBackend) -> None:
        settings = make_settings(models_path=tmp_path, vlm_backend=backend)
        write_model(settings)

        assert missing_model_files(settings) == []

    def test_a_folder_that_does_not_exist_misses_every_file(self, tmp_path: Path) -> None:
        settings = make_settings(models_path=tmp_path / "nowhere", vlm_backend="mlx")

        assert missing_model_files(settings) == list(MODEL_SPECS["mlx"].files)

    def test_an_incomplete_folder_names_exactly_the_files_that_are_absent(self, tmp_path: Path) -> None:
        settings = make_settings(models_path=tmp_path, vlm_backend="transformers")
        write_model(settings, skip=("model.safetensors", "chat_template.jinja"))

        assert missing_model_files(settings) == ["model.safetensors", "chat_template.jinja"]

    def test_a_directory_in_place_of_a_file_does_not_count(self, tmp_path: Path) -> None:
        settings = make_settings(models_path=tmp_path, vlm_backend="mlx")
        folder = write_model(settings, skip=("config.json",))
        (folder / "config.json").mkdir()

        assert missing_model_files(settings) == ["config.json"]

    def test_the_other_backends_folder_is_not_looked_in(self, tmp_path: Path) -> None:
        write_model(make_settings(models_path=tmp_path, vlm_backend="mlx"))

        assert missing_model_files(make_settings(models_path=tmp_path, vlm_backend="transformers")) == list(
            MODEL_SPECS["transformers"].files
        )


def test_building_the_parser_from_an_incomplete_folder_names_the_gap_before_loading_anything(tmp_path: Path) -> None:
    settings = make_settings(models_path=tmp_path, vlm_backend="mlx")
    write_model(settings, skip=("tokenizer.json",))

    with pytest.raises(ModelUnavailable, match=r"missing tokenizer\.json"):
        build_docling_parser(settings)
