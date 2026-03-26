"""
Health Check Sunucusu
GET /health → Sistem durumu JSON
"""

import json
import logging
import time
from datetime import datetime, timezone

from aiohttp import web

from src import config

logger = logging.getLogger(__name__)

_start_time = time.time()


def create_health_app(
    coin_supervisor=None,
    buffer=None,
    last_signal_time_ref: dict | None = None,
) -> web.Application:
    """aiohttp uygulaması oluştur."""
    app = web.Application()

    async def health_handler(request: web.Request) -> web.Response:
        return web.Response(
            content_type="application/json",
            text=json.dumps(
                _build_status(coin_supervisor, buffer, last_signal_time_ref),
                ensure_ascii=False,
                indent=2,
            ),
        )

    app.router.add_get("/health", health_handler)
    return app


def _build_status(coin_supervisor, buffer, last_signal_time_ref: dict | None) -> dict:
    """Durum sözlüğü oluştur."""
    uptime_sec = int(time.time() - _start_time)
    hours, rem = divmod(uptime_sec, 3600)
    minutes, seconds = divmod(rem, 60)
    uptime_str = f"{hours}s {minutes}dk {seconds}sn"

    # WebSocket durumları
    ws_status: dict[str, str] = {}
    connected_count = 0
    total_count = 6  # 6 borsa/tip kombinasyonu

    if coin_supervisor:
        ws_status = coin_supervisor.connection_status()
        connected_count = sum(
            1 for v in ws_status.values() if v == "bağlı"
        )
        total_count = len(ws_status) if ws_status else 6

    # Son sinyal zamanı
    last_signal_at = None
    if last_signal_time_ref and last_signal_time_ref.get("ts"):
        last_signal_at = datetime.fromtimestamp(
            last_signal_time_ref["ts"], tz=timezone.utc
        ).isoformat()

    # RAM kullanımı
    ram_mb = 0.0
    coin_count = 0
    if buffer:
        ram_mb = buffer.total_ram_mb()
        coin_count = len(buffer.coins())

    status = {
        "status": "ok" if connected_count >= 3 else "kritik",
        "uptime": uptime_str,
        "websockets": ws_status,
        "connected_count": f"{connected_count}/{total_count}",
        "last_signal_at": last_signal_at,
        "coin_count": coin_count,
        "ram_usage_gb": round(ram_mb / 1024, 3),
        "dry_run": config.is_dry_run(),
    }
    return status


async def run_health_server(
    coin_supervisor=None,
    buffer=None,
    last_signal_time_ref: dict | None = None,
) -> None:
    """Health check sunucusunu başlat."""
    host: str = config.get("health_check_host", "0.0.0.0")
    port: int = config.get("health_check_port", 8080)

    app = create_health_app(coin_supervisor, buffer, last_signal_time_ref)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("Health check sunucusu başlatıldı: http://%s:%d/health", host, port)
