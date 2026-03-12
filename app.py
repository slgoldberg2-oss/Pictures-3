"""
StreetShot — Cook County PIN Lookup & Street View PDF Generator
---------------------------------------------------------------
Local:   python app.py  →  http://localhost:5000
Railway: deployed via Dockerfile (mcr.microsoft.com/playwright/python)
"""

import io
import os
import traceback
import urllib.parse

import requests
from flask import Flask, jsonify, render_template, request, send_file

app = Flask(__name__)

PORT = int(os.environ.get("PORT", 5000))
SOCRATA_BASE = "https://datacatalog.cookcountyil.gov/resource/pabr-t5kh.json"


# ── Helpers ────────────────────────────────────────────────────────────────────

def normalize_pin(raw: str) -> str:
    """Strip dashes/spaces, zero-pad to 14 digits."""
    return raw.replace("-", "").replace(" ", "").zfill(14)


def lookup_pin(pin14: str) -> dict:
    """
    Query Cook County Parcel Universe for a PIN.
    Returns dict with pin14, lat, lon, address — or raises ValueError.
    """
    print(f"[PIN] Looking up: {pin14}")
    headers = {"Accept": "application/json"}

    urls = [
        f"{SOCRATA_BASE}?pin14={urllib.parse.quote(pin14)}&$limit=1",
        f"{SOCRATA_BASE}?$where=pin14='{pin14}'&$limit=1",
        f"{SOCRATA_BASE}?$where=pin='{pin14}'&$limit=1",
    ]

    row = None
    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if data and isinstance(data, list) and len(data) > 0:
                row = data[0]
                print(f"[PIN] Hit — fields: {list(row.keys())}")
                break
        except Exception as e:
            print(f"[PIN] URL failed: {e}")

    if not row:
        raise ValueError(f"PIN {pin14} not found in Cook County database")

    # Extract coordinates — field names vary across dataset versions
    lat = (row.get("lat") or row.get("latitude") or
           row.get("centroid_lat") or row.get("y_coordinate"))
    lon = (row.get("lon") or row.get("longitude") or
           row.get("centroid_lon") or row.get("x_coordinate"))

    # Socrata sometimes nests coords inside a "location" object
    if not lat and "location" in row:
        loc = row["location"]
        if isinstance(loc, dict):
            lat = loc.get("latitude") or loc.get("lat")
            lon = loc.get("longitude") or loc.get("lon")

    if not lat or not lon:
        raise ValueError(
            f"PIN {pin14} found but has no coordinates. "
            f"Available fields: {list(row.keys())}"
        )

    address = (
        row.get("prop_address_full") or
        row.get("property_address") or
        row.get("address") or
        f"PIN {pin14}"
    )

    return {"pin14": pin14, "lat": float(lat), "lon": float(lon), "address": address}


def capture_screenshot(lat: float, lon: float, label: str = "") -> bytes:
    """Open InstantStreetView at lat/lon and return a PNG screenshot."""
    from playwright.sync_api import sync_playwright

    url = f"https://www.instantstreetview.com/@{lat},{lon},0h,0p,1z"
    print(f"[CAP] {label} → {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
        except Exception as e:
            print(f"[CAP] Nav warning (continuing): {e}")

        # Wait for Street View canvas to render
        try:
            page.wait_for_selector("canvas", timeout=15000)
            page.wait_for_timeout(6000)
        except Exception:
            page.wait_for_timeout(8000)

        # Dismiss any overlays
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)
        except Exception:
            pass

        img_bytes = page.screenshot(type="png", full_page=False)
        browser.close()
        print(f"[CAP] Done — {len(img_bytes):,} bytes")
        return img_bytes


def build_combined_pdf(pages: list) -> bytes:
    """Assemble a multi-page PDF from a list of {label, png} dicts."""
    from PIL import Image
    from reportlab.lib.colors import Color
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as pdf_canvas

    buf = io.BytesIO()
    first = Image.open(io.BytesIO(pages[0]["png"]))
    iw, ih = first.size
    c = pdf_canvas.Canvas(buf, pagesize=(iw, ih))

    for i, page in enumerate(pages):
        png_bytes = page["png"]
        label = page.get("label", "")

        img = Image.open(io.BytesIO(png_bytes))
        pw, ph = img.size
        c.setPageSize((pw, ph))

        # Dark header bar
        bar_h = 40
        c.setFillColor(Color(0.1, 0.09, 0.07))
        c.rect(0, ph - bar_h, pw, bar_h, fill=1, stroke=0)

        # Page counter
        c.setFillColorRGB(0.78, 0.72, 0.60)
        c.setFont("Helvetica", 10)
        c.drawString(14, ph - bar_h + 14, f"({i + 1} of {len(pages)})")

        # Property label
        c.setFillColorRGB(0.95, 0.90, 0.84)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(14, ph - 22, label)

        # Street view image
        c.drawImage(ImageReader(io.BytesIO(png_bytes)), 0, 0, width=pw, height=ph - bar_h)

        if i < len(pages) - 1:
            c.showPage()

    c.save()
    buf.seek(0)
    return buf.read()


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    """Railway uses this to confirm the app is running."""
    return jsonify({"status": "ok"}), 200


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/lookup-pin", methods=["POST"])
def lookup_pin_route():
    data = request.get_json(silent=True) or {}
    raw_pin = data.get("pin", "").strip()
    if not raw_pin:
        return jsonify({"error": "No PIN provided"}), 400
    try:
        pin14 = normalize_pin(raw_pin)
        result = lookup_pin(pin14)
        return jsonify(result)
    except Exception as e:
        print(f"[LOOKUP] {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 404


@app.route("/generate-pdf", methods=["POST"])
def generate_pdf():
    data = request.get_json(silent=True) or {}
    properties = data.get("properties", [])

    if not properties:
        return jsonify({"error": "No properties provided"}), 400

    pages, errors = [], []

    for prop in properties:
        label = prop.get("label", "")
        raw_pin = prop.get("pin", "").strip()
        if not raw_pin:
            errors.append(f"{label}: no PIN entered")
            continue
        try:
            pin14 = normalize_pin(raw_pin)
            info = lookup_pin(pin14)
            print(f"[GEN] {label} lat={info['lat']} lon={info['lon']}")
            png = capture_screenshot(info["lat"], info["lon"], label=label)
            pages.append({
                "label": f"{label}  |  PIN {pin14}  |  {info['address']}",
                "png": png,
            })
        except Exception as e:
            print(f"[GEN] ERROR {label}: {traceback.format_exc()}")
            errors.append(f"{label} (PIN {raw_pin}): {str(e)}")

    if not pages:
        return jsonify({
            "error": "No properties captured. Errors: " + "; ".join(errors)
        }), 500

    pdf_bytes = build_combined_pdf(pages)
    print(f"[GEN] PDF complete — {len(pdf_bytes):,} bytes, {len(pages)} page(s)")

    resp = send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=False,
        download_name="streetview_properties.pdf",
    )
    if errors:
        resp.headers["X-Warnings"] = "; ".join(errors)
    return resp


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n{'=' * 55}")
    print("  StreetShot — Cook County PIN Street View Tool")
    print(f"  http://localhost:{PORT}")
    print(f"{'=' * 55}\n")
    app.run(host="0.0.0.0", port=PORT, debug=False)
