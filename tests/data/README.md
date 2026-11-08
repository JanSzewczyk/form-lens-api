# Test documents

Every file here is synthetic: generated for this repository, with no personal or real business
data. Each shows the same three lines, `FormLens synthetic sample`, `Invoice 2024-001` and
`Total: 120.00 EUR`.

| File | What it is |
| --- | --- |
| `text_layer.pdf` | One page with a real text layer, written by hand (Helvetica, no embedded font). |
| `scan.pdf` | One page that holds only a raster image of the text, so there is no text layer. |
| `sample.png`, `sample.jpg`, `sample.tiff` | The same lines as an image (520 x 160 px; the TIFF is grey, LZW). |

The fast tests only need the signature bytes and use a fake parser. The slow tests (`make test-models`)
read them with the real model. The images were drawn once with Pillow's default font and the files
committed; no test imports Pillow.
