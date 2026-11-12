import io
import os
import shutil
import time
import argparse

import numpy as np
import pymupdf
from PIL import Image

# quality: JPEG kalite arama aralığı, psnr: hedef doğruluk (dB), scan_dpi: tarama sayfası DPI tabanı
LEVELS = {
    "low":         {"dpi": 220, "scan_dpi": 300, "quality": (70, 92), "psnr": 41.0},
    "recommended": {"dpi": 150, "scan_dpi": 200, "quality": (50, 85), "psnr": 37.0},
    "high":        {"dpi": 96,  "scan_dpi": 150, "quality": (30, 75), "psnr": 33.0},
}

FALLBACK_MAX_PX = 2500
MIN_GAIN = 0.95
COVER_FOR_SCAN = 0.8

# ---------------------------------------------------------------- analiz
def _collect_images(doc):
    info = {}
    for page in doc:
        page_area = max(page.rect.width * page.rect.height, 1.0)
        for img in page.get_images(full=True):
            xref, w, h, bpc = img[0], img[2], img[3], img[4]
            cs, flt = str(img[5]), img[8] or ""
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                rects = []
            dpi, cover = 0.0, 0.0
            for r in rects:
                side = max(r.width, r.height)
                if side > 1:
                    dpi = max(dpi, max(w, h) / (side / 72.0))
                    cover = max(cover, (r.width * r.height) / page_area)
            e = info.setdefault(xref, {"dpi": 0.0, "cover": 0.0, "bpc": bpc, "filter": flt, "cs": cs})
            e["dpi"] = max(e["dpi"], dpi)
            e["cover"] = max(e["cover"], cover)
    return info

def _looks_like_document(img):
    s = img.resize((96, 96), Image.Resampling.BOX)
    lum = np.asarray(s.convert("L"))
    sat = np.asarray(s.convert("HSV"))[..., 1] if s.mode == "RGB" else np.zeros(1)
    return float(np.median(lum)) > 170 and float(np.mean(sat)) < 40

# ---------------------------------------------------------------- kodlama
def _psnr(a, b):
    x, y = np.asarray(a), np.asarray(b)
    if x.size > 6_000_000:
        x, y = x[::2, ::2], y[::2, ::2]
    d = x.astype(np.int16) - y.astype(np.int16)
    mse = float(np.mean(d.astype(np.float32) ** 2))
    return 99.0 if mse == 0 else 10.0 * np.log10(255.0 ** 2 / mse)

def _jpeg_bytes(img, q):
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=q, optimize=True, subsampling=0 if q >= 80 else -1)
    return buf.getvalue()

def _encode_adaptive(img, cfg):
    lo, hi = cfg["quality"]
    top, best = hi, None
    while lo <= hi:
        q = (lo + hi) // 2
        data = _jpeg_bytes(img, q)
        if _psnr(img, Image.open(io.BytesIO(data))) >= cfg["psnr"]:
            best, hi = data, q - 1
        else:
            lo = q + 1
    return best if best is not None else _jpeg_bytes(img, top)

def _recompress_image(doc, xref, meta, cfg, keep_print):
    try:
        if doc.xref_get_key(xref, "ImageMask")[1] == "true": return 0, "mask"
        if doc.xref_get_key(xref, "Mask")[0] != "null": return 0, "mask"
        if meta["bpc"] == 1 or "CCITT" in meta["filter"] or "JBIG2" in meta["filter"]: return 0, "1-bit scan"
        if "Indexed" in meta["cs"]: return 0, "graphic"

        old_len = len(doc.xref_stream_raw(xref))
        pix = pymupdf.Pixmap(doc, xref)
        if pix.colorspace is None or pix.alpha: return 0, "not applicable"
        if pix.width < 16 or pix.height < 16: return 0, "too small"
        
        if pix.n not in (1, 3):
            if keep_print: return 0, "CMYK preserved"
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)

        gray = pix.n == 1
        img = Image.frombytes("L" if gray else "RGB", (pix.width, pix.height), pix.samples)

        max_colors = 32 if gray else 256
        if img.resize((128, 128), Image.Resampling.NEAREST).getcolors(max_colors) is not None:
            return 0, "graphic"

        is_doc = meta["cover"] >= COVER_FOR_SCAN and _looks_like_document(img)
        target = cfg["scan_dpi"] if is_doc else cfg["dpi"]

        w, h = img.size
        scale = 1.0
        if meta["dpi"] > target * 1.2:
            scale = target / meta["dpi"]
        elif meta["dpi"] == 0 and max(w, h) > FALLBACK_MAX_PX:
            scale = FALLBACK_MAX_PX / max(w, h)
            
        if scale < 1.0:
            img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.LANCZOS)

        new_bytes = _encode_adaptive(img, cfg)
        if len(new_bytes) >= old_len * MIN_GAIN: return 0, "no gain"

        doc.update_stream(xref, new_bytes, new=False, compress=False)
        doc.xref_set_key(xref, "Filter", "/DCTDecode")
        doc.xref_set_key(xref, "ColorSpace", "/DeviceGray" if gray else "/DeviceRGB")
        doc.xref_set_key(xref, "BitsPerComponent", "8")
        for k in ("DecodeParms", "Decode", "ColorTransform"):
            doc.xref_set_key(xref, k, "null")
        doc.xref_set_key(xref, "Width", str(img.width))
        doc.xref_set_key(xref, "Height", str(img.height))
        
        return old_len - len(new_bytes), ("scan" if is_doc else "photo")
    except Exception:
        return 0, "error"

# ---------------------------------------------------------------- yapısal temizlik
def _strip_adobe_bloat(doc, keep_print_data=False):
    keys = ("PieceInfo", "Thumb") if keep_print_data else ("PieceInfo", "Thumb", "Metadata")
    for xref in range(1, doc.xref_length()):
        for key in keys:
            try:
                if doc.xref_get_key(xref, key)[0] != "null":
                    doc.xref_set_key(xref, key, "null")
            except Exception:
                pass
    if not keep_print_data:
        try:
            doc.xref_set_key(doc.pdf_catalog(), "OutputIntents", "null")
        except Exception:
            pass

def _save(doc, path, keep_print_data=False):
    kw = dict(garbage=4, deflate=True, deflate_fonts=True)
    if keep_print_data:
        doc.save(path, **kw)
        return
    try:
        doc.save(path, use_objstms=True, **kw)
    except TypeError:
        doc.save(path, **kw)

# ---------------------------------------------------------------- doğrulama
def _decode_failures(path):
    fails, seen = 0, set()
    d = pymupdf.open(path)
    try:
        if d.needs_pass: raise ValueError("PDF is encrypted.")
        for page in d:
            for img in page.get_images(full=True):
                if img[0] in seen: continue
                seen.add(img[0])
                try: pymupdf.Pixmap(d, img[0])
                except Exception: fails += 1
            try: page.get_pixmap(matrix=pymupdf.Matrix(0.25, 0.25))
            except Exception: fails += 1
    finally:
        d.close()
    return fails

# ---------------------------------------------------------------- ana akış
def _build(input_path, tmp, cfg, report, recompress=True, keep_print_data=False):
    doc = pymupdf.open(input_path)
    stats = {"pages": 0, "found": 0, "optimized": 0, "scans": 0, "image_saved": 0, "skipped": {}}
    try:
        if doc.needs_pass: raise ValueError("PDF is encrypted.")
        stats["pages"] = len(doc)

        if recompress:
            report(5, "Analyzing PDF...")
            images = _collect_images(doc)
            stats["found"] = len(images)
            total = max(len(images), 1)
            for i, (xref, meta) in enumerate(images.items()):
                saved, why = _recompress_image(doc, xref, meta, cfg, keep_print_data)
                if saved > 0:
                    stats["optimized"] += 1
                    stats["image_saved"] += saved
                    if why == "scan": stats["scans"] += 1
                else:
                    stats["skipped"][why] = stats["skipped"].get(why, 0) + 1
                report(8 + int((i + 1) / total * 77), f"Optimizing images ({i+1}/{total})...")

        report(88, "Cleaning structural bloat...")
        try: doc.subset_fonts()
        except Exception: pass
        
        try: _strip_adobe_bloat(doc, keep_print_data)
        except Exception: pass

        report(93, "Compiling optimized PDF...")
        _save(doc, tmp, keep_print_data)
    finally:
        doc.close()
    return stats

def compress_pdf(input_path, output_path, level="recommended", progress=None, keep_print_data=False):
    """
    Main entry point for compressing a PDF.
    Returns a dictionary containing statistics of the operation.
    """
    t0 = time.time()
    cfg = LEVELS.get(level, LEVELS["recommended"])
    report = progress or (lambda p, m: None)
    original_size = os.path.getsize(input_path)
    tmp = output_path + ".tmp"
    unchanged = fallback = False
    stats = {}

    try:
        report(2, "Preparing engine...")
        baseline = _decode_failures(input_path)
        stats = _build(input_path, tmp, cfg, report, True, keep_print_data)

        report(97, "Verifying integrity...")
        if _decode_failures(tmp) > baseline:
            fallback = True
            report(98, "Integrity check failed. Falling back to safe mode...")
            stats = _build(input_path, tmp, cfg, report, False, keep_print_data)

        if os.path.getsize(tmp) >= original_size:
            shutil.copyfile(input_path, output_path)
            unchanged = True
        else:
            os.replace(tmp, output_path)
    finally:
        if os.path.exists(tmp):
            try: os.remove(tmp)
            except OSError: pass

    return {
        "original_bytes": original_size,
        "compressed_bytes": os.path.getsize(output_path),
        "unchanged": unchanged,
        "fallback": fallback,
        "time_seconds": round(time.time() - t0, 1),
        "pages": stats.get("pages", 0),
        "images_found": stats.get("found", 0),
        "images_optimized": stats.get("optimized", 0),
        "scans_detected": stats.get("scans", 0),
        "bytes_saved_from_images": stats.get("image_saved", 0),
        "skipped_reasons": stats.get("skipped", {}),
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Adaptive PDF Compressor: Smart, safe, and efficient PDF optimization.")
    parser.add_argument("input", help="Path to the input PDF file")
    parser.add_argument("-o", "--output", help="Path to the output PDF file (default: input_compressed.pdf)", default=None)
    parser.add_argument("-l", "--level", choices=["low", "recommended", "high"], default="recommended", help="Compression level")
    parser.add_argument("--keep-print", action="store_true", help="Preserve CMYK profiles and prepress intents")
    
    args = parser.parse_args()
    
    out_path = args.output
    if not out_path:
        base, ext = os.path.splitext(args.input)
        out_path = f"{base}_compressed{ext}"
        
    def cli_progress(percent, message):
        print(f"[{percent:3d}%] {message}")
        
    print(f"\nStarting compression for: {args.input}")
    print(f"Level: {args.level} | Keep Print Data: {args.keep_print}\n")
    
    result = compress_pdf(args.input, out_path, level=args.level, progress=cli_progress, keep_print_data=args.keep_print)
    
    print("\n--- Compression Summary ---")
    orig_mb = result['original_bytes'] / (1024*1024)
    comp_mb = result['compressed_bytes'] / (1024*1024)
    
    if result["unchanged"] and not result["fallback"]:
        print("Result: File is already optimally compressed.")
    elif result["fallback"]:
        print("Result: Saved in Safe Mode (Images bypassed due to integrity failure).")
    else:
        saving = 100 - (result['compressed_bytes'] / result['original_bytes'] * 100)
        print(f"Result: Success! Reduced by {saving:.1f}%")
        
    print(f"Size: {orig_mb:.2f} MB -> {comp_mb:.2f} MB")
    print(f"Time: {result['time_seconds']} seconds")
    print(f"Images Optimized: {result['images_optimized']}/{result['images_found']}")
    if result["scans_detected"]:
        print(f"Scanned Pages Preserved: {result['scans_detected']}")
