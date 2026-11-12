# AdaptivePDFCompressor

An intelligent, context-aware PDF compression engine written in Python. 

Unlike standard "reduce file size" scripts that blindly convert everything to low-quality JPEGs, **AdaptivePDFCompressor** uses image matrix analysis and binary PSNR (Peak Signal-to-Noise Ratio) search to determine the perfect compression strategy for each unique element inside the PDF.

## 🌟 Key Features

* **Adaptive PSNR Binary Search:** Finds the absolute lowest JPEG quality required to maintain a target PSNR, preventing compression artifacts on smooth gradients while aggressively shrinking complex photos.
* **Smart Scan/Document Detection:** Analyzes image saturation and luminosity matrices. If it detects a scanned text document, it actively preserves a higher DPI baseline to ensure text remains perfectly readable.
* **Transparency & Mask Safety:** Automatically detects and safely bypasses `SMask` (soft masks), alpha channels, and 1-bit bitonal images (JBIG2/CCITT) to prevent Adobe Acrobat stream errors or black-background bugs.
* **Adobe Bloat Removal:** Safely strips unused `PieceInfo`, `Thumb`, and invisible metadata debris left behind by Adobe Illustrator and InDesign, often saving megabytes before touching a single pixel.
* **Integrity Fallback Validation:** Validates the final output using a matrix render test. If the compression breaks any internal PDF references, it automatically rolls back to a safe structural-only compression mode.

## 🚀 Installation

Ensure you have Python 3.9+ installed.

```bash
git clone [https://github.com/semihdrn/AdaptivePDFCompressor.git](https://github.com/semihdrn/AdaptivePDFCompressor.git)
cd AdaptivePDFCompressor
pip install -r requirements.txt
```

## 💻 Usage

### Command Line Interface (CLI)

You can run the engine directly from your terminal:

```bash
python adaptive_pdf_compressor.py input_document.pdf --level recommended
```

**Options:**
* `-o`, `--output`: Define custom output path (default is `input_compressed.pdf`).
* `-l`, `--level`: Choose compression level (`low`, `recommended`, `high`).
* `--keep-print`: Preserves CMYK color spaces and PDF/X OutputIntents for commercial printing.

### Use as a Python Module

You can easily integrate the engine into your own Python applications, servers, or GUI tools:

```python
from adaptive_pdf_compressor import compress_pdf

def my_progress_callback(percent, message):
    print(f"Progress: {percent}% - {message}")

results = compress_pdf(
    input_path="large_catalog.pdf",
    output_path="optimized_catalog.pdf",
    level="high",
    progress=my_progress_callback,
    keep_print_data=False
)

print(f"Optimization finished in {results['time_seconds']} seconds.")
print(f"Saved {(results['original_bytes'] - results['compressed_bytes']) / 1024 / 1024:.2f} MB!")
```

## 📊 How It Works Under The Hood

1. **Extraction:** PyMuPDF isolates every image and XObject.
2. **Analysis:** Pillow and NumPy calculate effective DPI, color space, and document-likeness.
3. **Re-encoding:** Images are iteratively compressed until the target PSNR is matched.
4. **Assembly:** Fonts are subsetted, garbage streams are collected, and the PDF is rebuilt with `deflate`.
5. **Verification:** The engine attempts to decode the newly compressed streams to guarantee cross-viewer compatibility.

## License
MIT License.
