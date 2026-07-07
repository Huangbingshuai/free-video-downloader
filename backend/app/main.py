from __future__ import annotations

import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    load_dotenv(_env_file)
else:
    load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.summaries import router as summaries_router
from app.routes.videos import router as videos_router

_pot_process: subprocess.Popen | None = None


def _start_pot_server() -> None:
    """启动 bgutil PO Token Provider 本地服务器。"""
    global _pot_process
    # 优先使用环境变量，否则使用项目内置的 pot_server
    pot_server_home = os.getenv("POT_SERVER_PATH", "").strip()
    if not pot_server_home:
        # 默认路径：backend/pot_server
        default_path = Path(__file__).resolve().parent.parent / "pot_server"
        if (default_path / "build" / "main.js").is_file():
            pot_server_home = str(default_path)
        else:
            print("[POT] POT server not found, skipping", file=sys.stderr)
            return

    server_js = Path(pot_server_home) / "build" / "main.js"
    if not server_js.is_file():
        print(f"[POT] Server script not found: {server_js}", file=sys.stderr)
        return

    env = os.environ.copy()
    # 传递系统代理给 Node.js 进程
    if "HTTPS_PROXY" not in env:
        env["HTTPS_PROXY"] = env.get("HTTP_PROXY", "")
        env["HTTP_PROXY"] = env.get("HTTP_PROXY", "")

    try:
        _pot_process = subprocess.Popen(
            ["node", str(server_js)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"[POT] Started bgutil POT server (PID {_pot_process.pid})")
    except Exception as exc:
        print(f"[POT] Failed to start POT server: {exc}", file=sys.stderr)


def _stop_pot_server() -> None:
    global _pot_process
    if _pot_process and _pot_process.poll() is None:
        _pot_process.terminate()
        try:
            _pot_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _pot_process.kill()
        print("[POT] Stopped bgutil POT server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _start_pot_server()
    yield
    _stop_pot_server()


app = FastAPI(
    title="Free Video Downloader API",
    description="A lightweight yt-dlp powered backend for public video downloads.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(videos_router)
app.include_router(summaries_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    pot_status = "running" if (_pot_process and _pot_process.poll() is None) else "stopped"
    return {"status": "ok", "pot_server": pot_status}
