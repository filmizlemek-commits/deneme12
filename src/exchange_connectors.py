"""
Phase 1 — Veri Toplayıcı
Borsa WebSocket/REST bağlantı kurucuları:
Binance Spot/Futures, Bybit Spot/Futures, OKX Spot/Futures
"""

import asyncio
import logging
import time

import aiohttp

from src import config
from src.ring_buffer import RingBufferManager
from src.ws_manager import WebSocketManager

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Mesaj ayrıştırıcılar
# ──────────────────────────────────────────────────────────────

def _parse_binance(name: str, data: dict, buffer: RingBufferManager) -> None:
    """Binance L2 emir defteri mesajını ayrıştır."""
    # {"lastUpdateId":..., "bids":[[price,qty],...], "asks":[[price,qty],...]}
    bids = [[float(p), float(q)] for p, q in data.get("bids", [])]
    asks = [[float(p), float(q)] for p, q in data.get("asks", [])]
    if not bids and not asks:
        return
    # name örneği: "binance_spot_BTCUSDT"
    parts = name.split("_", 2)
    market_type = parts[1]   # "spot" | "futures"
    coin = parts[2]          # "BTCUSDT"

    # Anlık fiyat: en iyi bid ortalaması
    if bids:
        buffer.update_extras(coin, last_price=bids[0][0])
    buffer.add_snapshot(coin, "binance", market_type, bids, asks)


def _parse_bybit(name: str, data: dict, buffer: RingBufferManager) -> None:
    """Bybit L2 emir defteri mesajını ayrıştır."""
    # {"topic":"orderbook.20.BTCUSDT","data":{"b":[[p,q],...],"a":[[p,q],...]}}
    inner = data.get("data", {})
    bids = [[float(p), float(q)] for p, q in inner.get("b", [])]
    asks = [[float(p), float(q)] for p, q in inner.get("a", [])]
    if not bids and not asks:
        return
    parts = name.split("_", 2)
    market_type = parts[1]
    coin = parts[2]
    if bids:
        buffer.update_extras(coin, last_price=bids[0][0])
    buffer.add_snapshot(coin, "bybit", market_type, bids, asks)


def _parse_okx(name: str, data: dict, buffer: RingBufferManager) -> None:
    """OKX L2 emir defteri mesajını ayrıştır."""
    # {"data":[{"bids":[[p,q,x,y],...], "asks":[[p,q,x,y],...]}]}
    items = data.get("data", [])
    if not items:
        return
    item = items[0]
    bids = [[float(row[0]), float(row[1])] for row in item.get("bids", [])]
    asks = [[float(row[0]), float(row[1])] for row in item.get("asks", [])]
    if not bids and not asks:
        return
    parts = name.split("_", 2)
    market_type = parts[1]
    coin = parts[2]
    if bids:
        buffer.update_extras(coin, last_price=bids[0][0])
    buffer.add_snapshot(coin, "okx", market_type, bids, asks)


# ──────────────────────────────────────────────────────────────
# Bağlantı fabrikası
# ──────────────────────────────────────────────────────────────

def create_binance_spot_manager(
    coin: str,
    buffer: RingBufferManager,
    telegram_notifier=None,
) -> WebSocketManager:
    symbol = coin.replace("/", "").lower()
    depth = config.get("orderbook_depth", 20)
    uri = f"wss://stream.binance.com/ws/{symbol}@depth{depth}@100ms"
    name = f"binance_spot_{coin.replace('/', '')}"

    async def on_message(n: str, data: dict) -> None:
        _parse_binance(n, data, buffer)

    return WebSocketManager(
        name=name,
        uri=uri,
        subscribe_msg={},   # Stream URI'ye gömülü
        on_message=on_message,
        telegram_notifier=telegram_notifier,
    )


def create_binance_futures_manager(
    coin: str,
    buffer: RingBufferManager,
    telegram_notifier=None,
) -> WebSocketManager:
    symbol = coin.replace("/", "").lower()
    depth = config.get("orderbook_depth", 20)
    uri = f"wss://fstream.binance.com/ws/{symbol}@depth{depth}@100ms"
    name = f"binance_futures_{coin.replace('/', '')}"

    async def on_message(n: str, data: dict) -> None:
        _parse_binance(n, data, buffer)

    return WebSocketManager(
        name=name,
        uri=uri,
        subscribe_msg={},
        on_message=on_message,
        telegram_notifier=telegram_notifier,
    )


def create_bybit_spot_manager(
    coin: str,
    buffer: RingBufferManager,
    telegram_notifier=None,
) -> WebSocketManager:
    symbol = coin.replace("/", "")
    depth = config.get("orderbook_depth", 20)
    uri = "wss://stream.bybit.com/v5/public/spot"
    name = f"bybit_spot_{symbol}"

    async def on_message(n: str, data: dict) -> None:
        _parse_bybit(n, data, buffer)

    return WebSocketManager(
        name=name,
        uri=uri,
        subscribe_msg={"op": "subscribe", "args": [f"orderbook.{depth}.{symbol}"]},
        on_message=on_message,
        telegram_notifier=telegram_notifier,
    )


def create_bybit_futures_manager(
    coin: str,
    buffer: RingBufferManager,
    telegram_notifier=None,
) -> WebSocketManager:
    symbol = coin.replace("/", "")
    depth = config.get("orderbook_depth", 20)
    uri = "wss://stream.bybit.com/v5/public/linear"
    name = f"bybit_futures_{symbol}"

    async def on_message(n: str, data: dict) -> None:
        _parse_bybit(n, data, buffer)

    return WebSocketManager(
        name=name,
        uri=uri,
        subscribe_msg={"op": "subscribe", "args": [f"orderbook.{depth}.{symbol}"]},
        on_message=on_message,
        telegram_notifier=telegram_notifier,
    )


def create_okx_spot_manager(
    coin: str,
    buffer: RingBufferManager,
    telegram_notifier=None,
) -> WebSocketManager:
    # OKX spot: BTC-USDT formatı
    inst_id = coin.replace("/", "-")
    depth = config.get("orderbook_depth", 20)
    uri = "wss://ws.okx.com:8443/ws/v5/public"
    name = f"okx_spot_{coin.replace('/', '')}"

    async def on_message(n: str, data: dict) -> None:
        _parse_okx(n, data, buffer)

    return WebSocketManager(
        name=name,
        uri=uri,
        subscribe_msg={
            "op": "subscribe",
            "args": [{"channel": f"books{depth}", "instId": inst_id}],
        },
        on_message=on_message,
        telegram_notifier=telegram_notifier,
    )


def create_okx_futures_manager(
    coin: str,
    buffer: RingBufferManager,
    telegram_notifier=None,
) -> WebSocketManager:
    # OKX futures: BTC-USDT-SWAP formatı
    inst_id = coin.replace("/", "-") + "-SWAP"
    depth = config.get("orderbook_depth", 20)
    uri = "wss://ws.okx.com:8443/ws/v5/public"
    name = f"okx_futures_{coin.replace('/', '')}"

    async def on_message(n: str, data: dict) -> None:
        _parse_okx(n, data, buffer)

    return WebSocketManager(
        name=name,
        uri=uri,
        subscribe_msg={
            "op": "subscribe",
            "args": [{"channel": f"books{depth}", "instId": inst_id}],
        },
        on_message=on_message,
        telegram_notifier=telegram_notifier,
    )


# ──────────────────────────────────────────────────────────────
# REST API — Ek veriler (funding, hacim, ATR)
# ──────────────────────────────────────────────────────────────

async def fetch_extras_loop(
    coins: list[str],
    buffer: RingBufferManager,
) -> None:
    """Her dakika funding rate, hacim değişimi ve ATR çek."""
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                for coin in coins:
                    await _fetch_binance_extras(session, coin, buffer)
        except Exception as exc:
            logger.error("Ek veri çekme hatası: %s", exc)
        await asyncio.sleep(60)


async def _fetch_binance_extras(
    session: aiohttp.ClientSession,
    coin: str,
    buffer: RingBufferManager,
) -> None:
    """Binance REST'ten funding rate ve hacim verisi çek."""
    symbol = coin.replace("/", "")

    # Funding rate
    try:
        url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                data = await resp.json()
                funding = float(data.get("lastFundingRate", 0)) * 100  # %'ye çevir
                buffer.update_extras(coin, funding_rate=funding)
    except Exception as exc:
        logger.debug("%s funding rate hatası: %s", coin, exc)

    # Son 5 dakika hacim değişimi (1m klines)
    try:
        url = (
            f"https://api.binance.com/api/v3/klines"
            f"?symbol={symbol}&interval=1m&limit=6"
        )
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                klines = await resp.json()
                if len(klines) >= 6:
                    vols = [float(k[5]) for k in klines]
                    avg_vol = sum(vols[:-1]) / max(len(vols) - 1, 1)
                    last_vol = vols[-1]
                    if avg_vol > 0:
                        change_pct = ((last_vol - avg_vol) / avg_vol) * 100
                        buffer.update_extras(coin, volume_change_pct=change_pct)

                    # ATR (basit hesaplama: son 14 mumun true range ortalaması)
                    if len(klines) >= 2:
                        trs = []
                        for i in range(1, len(klines)):
                            high = float(klines[i][2])
                            low = float(klines[i][3])
                            prev_close = float(klines[i - 1][4])
                            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                            trs.append(tr)
                        atr_val = sum(trs) / len(trs) if trs else 0.0
                        buffer.update_extras(coin, atr=atr_val)
    except Exception as exc:
        logger.debug("%s hacim/ATR hatası: %s", coin, exc)
