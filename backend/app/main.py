from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.videos import router as videos_router

app = FastAPI(
    title="Free Video Downloader API",
    description="A lightweight yt-dlp powered backend for public video downloads.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(videos_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
