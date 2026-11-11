"""A seeded generator of synthetic Polish forms with known answers.

Everything is made up. Names are invented, a PESEL starts with `000000` (month and day 00 do not exist, so it is
no one's), and every page says it is a test document. The same seed gives the same documents byte for byte on
the same Pillow version.

The set is varied on purpose: PDFs with a text layer and scans (PNG, JPEG, image-only PDF); a field that the
document does not show (the expected answer is `null`, and a model that invents a value is caught); numbers
and dates that look like the answer but are not (a postal code, a phone number, a payment due date); Polish
letters; amounts written the Polish way (`1 234,56`).
"""

import io
import json
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from tests.golden.pdf import image_pdf, text_pdf

SEED: Final = 20261111
KINDS: Final = ("text-pdf", "scan-png", "text-pdf", "scan-jpeg", "text-pdf", "scan-pdf")

_FIRST: Final = ("Anna", "Józef", "Małgorzata", "Łukasz", "Zdzisław", "Grażyna", "Ścibor", "Żaneta", "Błażej", "Ćwik")
_LAST: Final = (
    "Kowalska-Testowa",
    "Nowak-Przykładowy",
    "Wójcik-Fikcyjna",
    "Zieliński-Syntetyczny",
    "Dąbrowska-Testowa",
    "Szymański-Przykładowy",
)
_CITIES: Final = ("Łódź", "Kraków", "Gdańsk", "Wrocław", "Poznań", "Szczecin", "Bydgoszcz", "Lublin", "Białystok")
_COMPANIES: Final = (
    "Zakład Testowy Żuraw Sp. z o.o.",
    "Fikcyjna Piekarnia Łączka S.A.",
    "Przykładowe Usługi Ćmielów Sp. j.",
    "Syntetyczna Spółdzielnia Śnieżka",
    "Testowe Biuro Podróży Źródło",
)
_REMARKS: Final = (
    "Proszę o rozpatrzenie w trybie pilnym.",
    "Wyjazd służbowy do oddziału w Łodzi.",
    "Termin do uzgodnienia z kierownikiem.",
    "Dokumenty zostały złożone w sekretariacie.",
)
_NOTE: Final = "Dokument testowy. Dane syntetyczne, nie dotyczą żadnej osoby ani firmy."


@dataclass(frozen=True, slots=True)
class GoldenDocument:
    """One form: its file, what it shows and what a perfect extraction returns."""

    id: str
    template: str
    kind: str
    lines: tuple[str, ...]
    expected: dict[str, Any]
    content: bytes

    @property
    def extension(self) -> str:
        """Return the file extension of the document."""
        return {"text-pdf": "pdf", "scan-pdf": "pdf", "scan-png": "png", "scan-jpeg": "jpg"}[self.kind]


def _day(rng: random.Random) -> date:
    return date(2024, 1, 1) + timedelta(days=rng.randrange(0, 900))


def _pl(day: date) -> str:
    return f"{day.day:02d}.{day.month:02d}.{day.year}"


def _digits(rng: random.Random, count: int) -> str:
    return "".join(str(rng.randrange(10)) for _ in range(count))


def _omitted(rng: random.Random, names: tuple[str, ...], index: int) -> set[str]:
    """Pick the fields this document does not show: one in every third document, cycling through the fields.

    The cycle makes sure every field is absent in some document. Every sixth document (the 5th, 11th, ...) hides a
    second, random field too.
    """
    if index % 3 != 2:
        return set()
    first = names[(index // 3) % len(names)]
    omit = {first}
    if index % 6 == 5:
        omit.add(rng.choice([name for name in names if name != first]))
    return omit


def _consent(rng: random.Random, omit: set[str]) -> tuple[list[str], dict[str, Any]]:
    name = f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"
    pesel = "000000" + _digits(rng, 5)
    city = rng.choice(_CITIES)
    start, written = _day(rng), _day(rng)
    agreed = rng.random() < 0.7
    boxes = {True: "[X] TAK   [ ] NIE", False: "[ ] TAK   [X] NIE"}[agreed]
    lines = [
        "OŚWIADCZENIE O ZGODZIE NA PRZETWARZANIE DANYCH OSOBOWYCH",
        _NOTE,
        f"Imię i nazwisko: {name}" if "imie_nazwisko" not in omit else "Imię i nazwisko: ...................",
        f"PESEL: {pesel}" if "pesel" not in omit else "PESEL: ...........",
        f"Miejscowość: {city}" if "miasto" not in omit else "Miejscowość: ...................",
        (
            f"Kod pocztowy: {_digits(rng, 2)}-{_digits(rng, 3)}   Telefon: {_digits(rng, 9)}"
            f"   Dowód: ABC {_digits(rng, 6)}"
        ),
        f"Data obowiązywania od: {_pl(start)}" if "data_od" not in omit else "Data obowiązywania od: ../../....",
        f"Data sporządzenia: {_pl(written)}",
        f"Zgoda na przetwarzanie danych: {boxes}"
        if "zgoda" not in omit
        else "Zgoda na przetwarzanie danych: [ ] TAK   [ ] NIE",
    ]
    expected = {
        "pesel": None if "pesel" in omit else pesel,
        "data_od": None if "data_od" in omit else start.isoformat(),
        "zgoda": None if "zgoda" in omit else agreed,
        "imie_nazwisko": None if "imie_nazwisko" in omit else name,
        "miasto": None if "miasto" in omit else city,
    }
    return lines, expected


def _polish_amount(value: float) -> str:
    whole, cents = f"{value:.2f}".split(".")
    groups: list[str] = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    return " ".join([whole, *groups]) + "," + cents


def _invoice(rng: random.Random, omit: set[str]) -> tuple[list[str], dict[str, Any]]:
    if "kwota_brutto" in omit:
        omit = omit | {"waluta"}  # the currency is written with the total
    number = f"FV/{rng.randrange(1, 400)}/{rng.choice((2025, 2026))}"
    issued, due = _day(rng), _day(rng)
    buyer = rng.choice(_COMPANIES)
    total = round(rng.uniform(80, 25000), 2)
    currency = rng.choice(("PLN", "EUR"))
    paid = rng.random() < 0.5
    status = "ZAPŁACONO" if paid else "DO ZAPŁATY"
    lines = [
        f"FAKTURA VAT nr {number}" if "numer_faktury" not in omit else "FAKTURA VAT",
        _NOTE,
        f"Data wystawienia: {_pl(issued)}" if "data_wystawienia" not in omit else "Data wystawienia:",
        f"Termin płatności: {_pl(due)}",
        f"Nabywca: {buyer}" if "nabywca" not in omit else "Nabywca:",
        f"NIP: 000{_digits(rng, 7)}   Konto: 00 0000 0000 {_digits(rng, 4)}",
        f"Lp. 1   Usługa testowa   1 szt.   {_polish_amount(total * 0.81)}",
        f"Razem netto: {_polish_amount(total * 0.81)}",
    ]
    if "kwota_brutto" not in omit:
        written_currency = "" if "waluta" in omit else f" {currency}"
        lines.append(f"Razem do zapłaty brutto: {_polish_amount(total)}{written_currency}")
    if "zaplacono" not in omit:
        lines.append(f"Status płatności: {status}")
    expected = {
        "numer_faktury": None if "numer_faktury" in omit else number,
        "data_wystawienia": None if "data_wystawienia" in omit else issued.isoformat(),
        "nabywca": None if "nabywca" in omit else buyer,
        "kwota_brutto": None if "kwota_brutto" in omit else total,
        "waluta": None if "waluta" in omit else currency,
        "zaplacono": None if "zaplacono" in omit else paid,
    }
    return lines, expected


def _request(rng: random.Random, omit: set[str]) -> tuple[list[str], dict[str, Any]]:
    number = f"WN-{rng.randrange(1, 9000):04d}/2026"
    submitted = _day(rng)
    people = rng.randrange(1, 9)
    kind = rng.choice(("urlop", "zwolnienie", "delegacja"))
    remark = rng.choice(_REMARKS)
    lines = [
        f"WNIOSEK nr {number}" if "numer_wniosku" not in omit else "WNIOSEK",
        _NOTE,
        f"Data złożenia: {_pl(submitted)}" if "data_zlozenia" not in omit else "Data złożenia:",
        f"Pokój: {rng.randrange(1, 40)}   Telefon kontaktowy: {_digits(rng, 9)}",
    ]
    if "liczba_osob" not in omit:
        lines.append(f"Liczba osób: {people}")
    if "rodzaj" not in omit:
        lines.append(f"Rodzaj wniosku: {kind}")
    if "uwagi" not in omit:
        lines.append(f"Uwagi: {remark}")
    expected = {
        "numer_wniosku": None if "numer_wniosku" in omit else number,
        "data_zlozenia": None if "data_zlozenia" in omit else submitted.isoformat(),
        "liczba_osob": None if "liczba_osob" in omit else people,
        "rodzaj": None if "rodzaj" in omit else kind,
        "uwagi": None if "uwagi" in omit else remark,
    }
    return lines, expected


# The default font of Pillow has no Polish letters (it draws a box), and a system font would make the set depend
# on the machine. So the letters are built from a base letter and a mark that is drawn: no font file needed.
_BASE: Final = {
    "ą": ("a", "ogonek"), "Ą": ("A", "ogonek"), "ć": ("c", "acute"), "Ć": ("C", "acute"),
    "ę": ("e", "ogonek"), "Ę": ("E", "ogonek"), "ł": ("l", "stroke"), "Ł": ("L", "stroke"),
    "ń": ("n", "acute"), "Ń": ("N", "acute"), "ó": ("o", "acute"), "Ó": ("O", "acute"),
    "ś": ("s", "acute"), "Ś": ("S", "acute"), "ź": ("z", "acute"), "Ź": ("Z", "acute"),
    "ż": ("z", "dot"), "Ż": ("Z", "dot"),
}  # fmt: skip


def _draw_line(
    draw: ImageDraw.ImageDraw, x: float, y: float, text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont
) -> None:
    """Draw `text` at (x, y), building each Polish letter from its base letter and a drawn mark."""
    for char in text:
        base, mark = _BASE.get(char, (char, ""))
        draw.text((x, y), base, font=font, fill=20)
        left, top, right, bottom = (x + edge if i % 2 == 0 else y + edge for i, edge in enumerate(font.getbbox(base)))
        centre = (left + right) / 2
        if mark == "acute":
            draw.line([(centre - 3, top - 3), (centre + 5, top - 12)], fill=20, width=3)
        elif mark == "dot":
            draw.ellipse([centre - 3, top - 12, centre + 3, top - 6], fill=20)
        elif mark == "ogonek":
            draw.line([(right - 7, bottom), (right - 3, bottom + 8), (right + 4, bottom + 7)], fill=20, width=3)
        elif mark == "stroke":
            draw.line([(centre - 7, bottom - 8), (centre + 7, top + 10)], fill=20, width=3)
        x += font.getlength(base)


def render_scan(lines: tuple[str, ...], rng: random.Random, fmt: str) -> bytes:
    """Draw `lines` as a scanned page: a slight tilt, a little blur and a few specks, saved as PNG, JPEG or PDF."""
    font = ImageFont.load_default(size=30)
    page = Image.new("L", (1500, 120 + 52 * len(lines)), 255)
    draw = ImageDraw.Draw(page)
    for number, line in enumerate(lines):
        _draw_line(draw, 60, 60 + 52 * number, line, font)
    page = page.rotate(rng.uniform(-1.0, 1.0), expand=False, fillcolor=255, resample=Image.Resampling.BICUBIC)
    page = page.filter(ImageFilter.GaussianBlur(0.6))
    specks = ImageDraw.Draw(page)
    for _ in range(60):
        x, y = rng.randrange(page.width), rng.randrange(page.height)
        specks.point((x, y), fill=rng.randrange(120, 200))
    out = io.BytesIO()
    if fmt == "png":
        page.save(out, "PNG")
    else:
        page.save(out, "JPEG", quality=85)
    if fmt == "pdf":
        return image_pdf(out.getvalue(), page.width, page.height)
    return out.getvalue()


def generate(*, seed: int = SEED, per_template: int = 16) -> list[GoldenDocument]:
    """Return `per_template` documents of each template, the same ones for the same seed."""
    rng = random.Random(seed)  # noqa: S311  # a test-data generator, not a secret
    documents: list[GoldenDocument] = []
    builders = (
        ("zgoda", ("pesel", "data_od", "zgoda", "imie_nazwisko", "miasto"), _consent),
        ("faktura", ("numer_faktury", "zaplacono", "kwota_brutto", "nabywca", "data_wystawienia", "waluta"), _invoice),
        ("wniosek", ("numer_wniosku", "data_zlozenia", "liczba_osob", "rodzaj", "uwagi"), _request),
    )
    for key, names, build in builders:
        for index in range(per_template):
            omit = _omitted(rng, names, index)
            lines, expected = build(rng, omit)
            kind = KINDS[(len(documents)) % len(KINDS)]
            frozen = tuple(lines)
            content = (
                text_pdf(list(frozen))
                if kind == "text-pdf"
                else render_scan(frozen, rng, kind.removeprefix("scan-").replace("jpeg", "jpg"))
            )
            documents.append(GoldenDocument(f"{key}-{index:02d}", key, kind, frozen, expected, content))
    return documents


def export(documents: list[GoldenDocument], directory: Path) -> None:
    """Write each document and its expected answer (`<id>.expected.json`) to `directory`."""
    directory.mkdir(parents=True, exist_ok=True)
    for document in documents:
        (directory / f"{document.id}.{document.extension}").write_bytes(document.content)
        (directory / f"{document.id}.expected.json").write_text(
            json.dumps(document.expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
