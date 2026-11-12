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
git clone [https://github.com/YOUR_USERNAME/AdaptivePDFCompressor.git](https://github.com/YOUR_USERNAME/AdaptivePDFCompressor.git)
cd AdaptivePDFCompressor
pip install -r requirements.txt
