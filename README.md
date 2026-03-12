# StreetShot — Cook County PIN Street View PDF Generator

Enter up to 5 Cook County Property Index Numbers (PINs). The app looks up each property in the Cook County Assessor database, captures a street-level photo via InstantStreetView.com, and generates a single multi-page PDF ordered: Subject Property, Comparable 1–4.

---

## Run Locally

**1. Install dependencies**
```bash
pip install -r requirements.txt
playwright install chromium
```

**2. Start the server**
```bash
python app.py
```

**3. Open in browser**
```
http://localhost:5000
```

---

## Deploy to Railway

### Step 1 — Push to GitHub
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/streetshot.git
git push -u origin main
```

### Step 2 — Deploy on Railway
1. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
2. Select your repository
3. Railway detects the `Dockerfile` automatically and builds it
4. Your live URL appears in the Railway dashboard (~5 min build time)

> The Dockerfile uses `mcr.microsoft.com/playwright/python:v1.40.0-jammy` as the base image — this has Chromium and all system dependencies pre-installed, making the build reliable and fast.

---

## Project Structure

```
streetshot/
├── app.py                  # Flask server — API routes, screenshot, PDF logic
├── templates/
│   └── index.html          # Frontend UI
├── Dockerfile              # Uses official Playwright image (Chromium included)
├── requirements.txt        # Python dependencies
├── Procfile                # Fallback start command
├── .gitignore
└── README.md
```

---

## How It Works

1. User enters PINs (with or without dashes — both work)
2. Each PIN is validated live against the Cook County Assessor database
3. On **Generate PDF**, the server:
   - Queries `datacatalog.cookcountyil.gov` for lat/lon of each PIN
   - Opens `instantstreetview.com/@{lat},{lon}` in headless Chromium
   - Waits for Street View tiles to render, takes a PNG screenshot
   - Assembles all screenshots into a labeled multi-page PDF
4. PDF downloads automatically — one page per property, in order

---

## Dependencies

| Package | Purpose |
|---|---|
| Flask | Web framework |
| gunicorn | Production WSGI server |
| Playwright | Headless Chromium browser |
| Pillow | Image processing |
| ReportLab | PDF generation |
| Requests | Cook County Socrata API calls |
