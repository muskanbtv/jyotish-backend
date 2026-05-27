# Jyotish Dasha API — Deployment Guide

## Local Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here
uvicorn main:app --reload --port 8000
```

## Swiss Ephemeris Data Files

The backend uses `pyswisseph`. On Ubuntu/Debian:
```bash
apt install libswe-dev
# or point swe.set_ephe_path() to your .se1 files directory
```
Download ephemeris files from: https://www.astro.com/ftp/swisseph/ephe/

## Deploy to Railway (recommended, free tier)

1. Push this folder to a GitHub repo
2. Go to railway.app → New Project → Deploy from GitHub
3. Add environment variable: `ANTHROPIC_API_KEY=your_key`
4. Railway auto-detects FastAPI and deploys

## Deploy to Render

1. Push to GitHub
2. render.com → New Web Service → Connect repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Add env var: `ANTHROPIC_API_KEY`

## API Endpoints

### POST /chart
Free endpoint — returns raw chart data (Dasha sequence, planetary positions).
```json
{
  "name": "Arjun Sharma",
  "dob": "1990-03-15",
  "tob": "06:30",
  "lat": 31.1048,
  "lon": 77.1734,
  "tz_offset": 5.5
}
```

### POST /reading
Paid endpoint — returns full AI-generated reading.
Same body as /chart. Pass `anthropic_api_key` in body OR set env var.

### GET /health
Health check.

## Monetisation Flow

1. User fills birth form → frontend calls `/chart` (free)
2. User sees Dasha timeline preview → clicks "Unlock"
3. Payment via Razorpay → on success, call `/reading`
4. Stream reading to user + email PDF

## Razorpay Integration (quick start)

```javascript
const rzp = new Razorpay({
  key: 'rzp_live_xxx',
  amount: 29900, // paise
  currency: 'INR',
  name: 'Jyotish Dasha Reading',
  handler: async (response) => {
    // Verify payment server-side, then call /reading
    const reading = await fetch('/reading', { method:'POST', body: JSON.stringify(birthData) });
  }
});
rzp.open();
```
