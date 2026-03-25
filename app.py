"""
Sharp CBB Analyzer — FastAPI Backend
---------------------------------------
Serves the web UI and provides a single SSE endpoint that:
  1. Scrapes VSIN (DK + Circa) and OddsTrader (spreads + totals) via Playwright
  2. Runs the tiered sharp-money filtering pipeline
  3. Streams progress events to the browser
  4. Returns the filtered plays + formatted Gemini prompt
"""

import asyncio
import json
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from scrapers import scrape_vsin, scrape_oddstrader, scrape_tsi
from parsers import parse_tsi
from pipeline import run_pipeline, PROMPT_MAX_PLAYS
from prompt import build_prompt

app = FastAPI(title="Sharp CBB Analyzer")

# Mount static files (index.html lives here)
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

# Simple global lock: only one analysis runs at a time
_analysis_running = False


def _sse_event(event_type: str, data) -> dict:
    return {"event": event_type, "data": json.dumps(data)}


@app.get("/", response_class=HTMLResponse)
async def root():
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return FileResponse(html_path)
    return HTMLResponse("<h1>index.html not found</h1>", status_code=404)


@app.get("/api/analyze")
async def analyze(request: Request, sport: str = "cbb"):
    """
    SSE endpoint. Streams progress messages and final result.
    Event types: 'progress', 'result', 'error'
    Query params:
      sport: 'cbb' (default) or 'nba'
    """
    global _analysis_running
    sport = sport.lower() if sport.lower() in ("cbb", "nba") else "cbb"

    async def event_stream():
        global _analysis_running

        if _analysis_running:
            yield _sse_event("error", {
                "message": "Analysis already in progress. Please wait and try again."
            })
            return

        _analysis_running = True
        try:
            # --- Step 1: VSIN ---
            yield _sse_event("progress", {"message": "Fetching VSIN DraftKings splits..."})
            try:
                dk_text, circa_text = await asyncio.wait_for(
                    scrape_vsin(sport), timeout=30
                )
            except asyncio.TimeoutError:
                yield _sse_event("error", {
                    "message": (
                        "Timed out after 30s fetching VSIN splits "
                        "(stuck on DraftKings or Circa Sports page). "
                        "The VSIN site may be slow or down — try again."
                    )
                })
                return
            except Exception as e:
                yield _sse_event("error", {"message": f"Failed to fetch VSIN data: {e}"})
                return

            if not circa_text.strip():
                yield _sse_event("progress", {
                    "message": "Circa Sports data unavailable — will use DraftKings only."
                })
            else:
                yield _sse_event("progress", {"message": "VSIN Circa Sports splits fetched."})

            # Check if client disconnected
            if await request.is_disconnected():
                return

            # --- Step 2: OddsTrader ---
            yield _sse_event("progress", {"message": "Fetching OddsTrader spreads & totals..."})
            try:
                spreads_text, totals_text = await asyncio.wait_for(
                    scrape_oddstrader(sport), timeout=30
                )
            except asyncio.TimeoutError:
                yield _sse_event("error", {
                    "message": (
                        "Timed out after 30s fetching OddsTrader lines "
                        "(stuck on spreads or totals page). "
                        "The OddsTrader site may be slow or down — try again."
                    )
                })
                return
            except Exception as e:
                yield _sse_event("error", {"message": f"Failed to fetch OddsTrader data: {e}"})
                return

            if await request.is_disconnected():
                return

            # --- Step 2b: TSI Projections (CBB only, optional, non-blocking) ---
            tsi_projections, tsi_bets = [], []
            if sport == "cbb":
                yield _sse_event("progress", {"message": "Fetching TSI projections..."})
                try:
                    tsi_results = await asyncio.wait_for(scrape_tsi(), timeout=90)
                    for url, raw_text in tsi_results:
                        projs, bets = parse_tsi(raw_text)
                        tsi_projections.extend(projs)
                        tsi_bets.extend(bets)
                    if tsi_projections:
                        yield _sse_event("progress", {
                            "message": f"TSI: {len(tsi_projections)} projections, {len(tsi_bets)} bets loaded."
                        })
                    else:
                        yield _sse_event("progress", {"message": "No TSI projections found for today."})
                except Exception as e:
                    yield _sse_event("progress", {"message": f"TSI fetch failed (non-fatal): {e}"})

            if await request.is_disconnected():
                return

            # --- Step 3: Analysis ---
            yield _sse_event("progress", {"message": "Running game-driven analysis..."})
            try:
                plays = run_pipeline(
                    dk_text, circa_text, spreads_text, totals_text,
                    tsi_projections=tsi_projections, tsi_bets=tsi_bets,
                    sport=sport,
                )
            except Exception as e:
                yield _sse_event("error", {"message": f"Analysis failed: {e}"})
                return

            if not plays:
                yield _sse_event("result", {
                    "plays": [],
                    "prompt": "",
                    "message": (
                        "No games with sharp indicators or TSI edges found for today's slate. "
                        "Try again later — splits data builds up closer to game time."
                    ),
                })
                return

            # --- Step 4: Build prompt (top PROMPT_MAX_PLAYS with a Bovada line only) ---
            prompt_plays = [p for p in plays if p.bovada_line][:PROMPT_MAX_PLAYS]
            yield _sse_event("progress", {
                "message": (
                    f"Found {len(plays)} sharp play(s). "
                    f"Top {len(prompt_plays)} go into the Gemini prompt..."
                )
            })
            try:
                prompt = build_prompt(prompt_plays, sport=sport)
            except Exception as e:
                yield _sse_event("error", {"message": f"Prompt build failed: {e}"})
                return

            prompt_play_ids = {id(p) for p in prompt_plays}
            plays_dicts = []
            for p in plays:
                d = p.to_dict()
                d["in_prompt"] = id(p) in prompt_play_ids
                plays_dicts.append(d)

            yield _sse_event("result", {
                "plays": plays_dicts,
                "prompt_play_count": len(prompt_plays),
                "prompt": prompt,
                "message": f"Done. {len(plays)} play(s) found, top {len(prompt_plays)} in prompt.",
            })

        finally:
            _analysis_running = False

    return EventSourceResponse(event_stream())


@app.get("/api/status")
async def status():
    return {"running": _analysis_running}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
