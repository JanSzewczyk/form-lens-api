"""A one-page PDF with a real text layer, written by hand: Helvetica, no embedded font.

The Polish letters Helvetica's WinAnsi encoding lacks are mapped by name (`/aogonek`, `/Lslash`, ...) in a
`/Differences` array, so a reader that extracts text gets the right Unicode back. Written by hand, like
`tests/data/text_layer.pdf`, so the golden set needs no PDF library; `test_generator.py` reads the files with
pdfium to show the text comes back exactly.
"""

from typing import Final

_GLYPHS: Final = {
    "Ą": "Aogonek",
    "ą": "aogonek",
    "Ć": "Cacute",
    "ć": "cacute",
    "Ę": "Eogonek",
    "ę": "eogonek",
    "Ł": "Lslash",
    "ł": "lslash",
    "Ń": "Nacute",
    "ń": "nacute",
    "Ś": "Sacute",
    "ś": "sacute",
    "Ź": "Zacute",
    "ź": "zacute",
    "Ż": "Zdotaccent",
    "ż": "zdotaccent",
}
_CODES: Final = {char: 128 + index for index, char in enumerate(_GLYPHS)}


def _encode(text: str) -> bytes:
    out = bytearray()
    for char in text:
        out += bytes([_CODES[char]]) if char in _CODES else char.encode("cp1252")
    return bytes(out)


def _escape(raw: bytes) -> bytes:
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _assemble(objects: list[bytes]) -> bytes:
    """Number the objects, write the cross-reference table and the trailer."""
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    table = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{table}\n%%EOF\n".encode()
    return bytes(out)


def image_pdf(jpeg: bytes, width: int, height: int, *, dpi: int = 150) -> bytes:
    """Return a one-page PDF that holds only the picture `jpeg`, so it has no text layer (a scan).

    Written by hand, not with Pillow's PDF driver, because that one stamps the current time into the file.
    """
    page_width, page_height = width * 72 // dpi, height * 72 // dpi
    shown = b"q %d 0 0 %d 0 0 cm /Im0 Do Q" % (page_width, page_height)
    return _assemble(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents 4 0 R "
                b"/Resources << /XObject << /Im0 5 0 R >> >> >>"
            )
            % (page_width, page_height),
            b"<< /Length %d >>\nstream\n" % len(shown) + shown + b"\nendstream",
            (
                b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray "
                b"/BitsPerComponent 8 /Filter /DCTDecode /Length %d >>\nstream\n"
            )
            % (width, height, len(jpeg))
            + jpeg
            + b"\nendstream",
        ]
    )


def text_pdf(lines: list[str], *, size: int = 13) -> bytes:
    """Return a PDF page that shows `lines`, one under the other, as selectable text."""
    shown = b"".join(b"(" + _escape(_encode(line)) + b") Tj T* " for line in lines)
    stream = b"BT /F1 %d Tf 50 790 Td %d TL " % (size, size + 6) + shown + b"ET"
    differences = " ".join(f"/{name}" for name in _GLYPHS.values())
    font = (
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding << /Type /Encoding "
        f"/BaseEncoding /WinAnsiEncoding /Differences [128 {differences}] >> >>"
    ).encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        font,
    ]
    return _assemble(objects)
