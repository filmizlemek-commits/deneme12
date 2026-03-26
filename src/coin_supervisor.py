"""
Phase 1 — Veri Toplayıcı
CoinSupervisor: Coin listesini dinamik olarak yönetir.
WebSocket subscription'larını sıfırlamadan coin ekler/çıkarır.
"""

import asyncio
import logging

import aiohttp

from src import config
from src.exchange_connectors import (
    create_binance_spot_manager,
    create_binance_futures_manager,
    create_bybit_spot_manager,
    create_bybit_futures_manager,
    create_okx_spot_manager,
    create_okx_futures_manager,
    fetch_extras_loop,
)
from src.ring_buffer import RingBufferManager
from src.ws_manager import WebSocketManager, ConnectionStatus

logger = logging.getLogger(__name__)

# Desteklenen sabit coin listesi (başlangıç)
_DEFAULT_COINS = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
    "ADA/USDT", "AVAX/USDT", "DOGE/USDT", "MATIC/USDT", "DOT/USDT",
    "LTC/USDT", "LINK/USDT", "UNI/USDT", "ATOM/USDT", "ETC/USDT",
    "XLM/USDT", "NEAR/USDT", "APT/USDT", "OP/USDT", "ARB/USDT",
    "INJ/USDT", "SUI/USDT", "TIA/USDT", "PEPE/USDT", "WLD/USDT",
    "FIL/USDT", "SAND/USDT", "MANA/USDT", "GALA/USDT", "AXS/USDT",
    "RUNE/USDT", "FTM/USDT", "CRV/USDT", "LDO/USDT", "AAVE/USDT",
    "SNX/USDT", "COMP/USDT", "MKR/USDT", "ENS/USDT", "1INCH/USDT",
    "GRT/USDT", "CHZ/USDT", "MINA/USDT", "FLOW/USDT", "KAVA/USDT",
    "ZIL/USDT", "THETA/USDT", "VET/USDT", "IOTA/USDT", "NEO/USDT",
]


class CoinSupervisor:
    """
    Coin listesini yönetir ve WebSocket aboneliklerini dinamik günceller.
    Tam restart olmadan coin ekler/çıkarır.
    """

    def __init__(
        self,
        buffer: RingBufferManager,
        telegram_notifier=None,
    ) -> None:
        self.buffer = buffer
        self.telegram_notifier = telegram_notifier
        self._coins: set[str] = set()
        # coin → {manager_name: WebSocketManager}
        self._managers: dict[str, dict[str, WebSocketManager]] = {}
        self._extras_task: asyncio.Task | None = None

    # ──────────────────────────────────────────────
    # Başlatma / durdurma
    # ──────────────────────────────────────────────

    async def start(self, initial_coins: list[str] | None = None) -> None:
        """İlk coin listesiyle başlat."""
        coins = initial_coins or _DEFAULT_COINS
        for coin in coins:
            await self._add_coin(coin)

        # Ek veri döngüsünü başlat
        self._extras_task = asyncio.create_task(
            fetch_extras_loop(list(self._coins), self.buffer),
            name="extras_loop",
        )
        logger.info("CoinSupervisor başlatıldı: %d coin aktif.", len(self._coins))

    async def stop(self) -> None:
        """Tüm bağlantıları kapat."""
        if self._extras_task:
            self._extras_task.cancel()
        for coin in list(self._coins):
            await self._remove_coin(coin)
        logger.info("CoinSupervisor durduruldu.")

    # ──────────────────────────────────────────────
    # Dinamik güncelleme
    # ──────────────────────────────────────────────

    async def update_coin_list(self, new_coins: list[str]) -> None:
        """
        Yeni coin listesiyle güncelle:
        - Eklenen coinler için yeni WS başlat
        - Çıkan coinler için WS kapat + buffer temizle
        """
        new_set = set(new_coins)
        to_add = new_set - self._coins
        to_remove = self._coins - new_set

        for coin in to_remove:
            await self._remove_coin(coin)

        for coin in to_add:
            await self._add_coin(coin)

        if to_add or to_remove:
            logger.info(
                "Coin listesi güncellendi. Eklenen: %d, Çıkan: %d. Aktif: %d",
                len(to_add), len(to_remove), len(self._coins),
            )

        # Extras döngüsünü yeniden başlat (güncel coin listesiyle)
        if to_add or to_remove:
            if self._extras_task:
                self._extras_task.cancel()
            self._extras_task = asyncio.create_task(
                fetch_extras_loop(list(self._coins), self.buffer),
                name="extras_loop",
            )

    async def _add_coin(self, coin: str) -> None:
        """Coin için 6 WebSocket yöneticisi oluştur ve başlat."""
        if coin in self._coins:
            return

        managers = {
            "binance_spot":    create_binance_spot_manager(coin, self.buffer, self.telegram_notifier),
            "binance_futures": create_binance_futures_manager(coin, self.buffer, self.telegram_notifier),
            "bybit_spot":      create_bybit_spot_manager(coin, self.buffer, self.telegram_notifier),
            "bybit_futures":   create_bybit_futures_manager(coin, self.buffer, self.telegram_notifier),
            "okx_spot":        create_okx_spot_manager(coin, self.buffer, self.telegram_notifier),
            "okx_futures":     create_okx_futures_manager(coin, self.buffer, self.telegram_notifier),
        }

        for mgr in managers.values():
            await mgr.start()

        self._managers[coin] = managers
        self._coins.add(coin)
        logger.debug("Coin eklendi: %s", coin)

    async def _remove_coin(self, coin: str) -> None:
        """Coin için tüm WebSocket bağlantılarını kapat ve buffer'ı temizle."""
        if coin not in self._coins:
            return

        managers = self._managers.pop(coin, {})
        for mgr in managers.values():
            await mgr.stop()

        self.buffer.remove_coin(coin)
        self._coins.discard(coin)
        logger.debug("Coin kaldırıldı: %s", coin)

    # ──────────────────────────────────────────────
    # Durum sorgulama
    # ──────────────────────────────────────────────

    def active_coins(self) -> list[str]:
        return sorted(self._coins)

    def connection_status(self) -> dict[str, str]:
        """Her ana bağlantı türü için durum döndür (ilk coin üzerinden)."""
        status: dict[str, str] = {}
        # İlk coinin manager durumlarını global durum göstergesi olarak kullan
        first_managers = next(iter(self._managers.values()), {}) if self._managers else {}
        for key, mgr in first_managers.items():
            # key: "binance_spot", "binance_futures" vb.
            parts = key.split("_", 1)
            exchange = parts[0]
            mtype = parts[1] if len(parts) > 1 else key
            status_key = f"{exchange}_{mtype}"
            status[status_key] = mgr.status.value
        return status

    def connected_count(self) -> int:
        """Bağlı WebSocket sayısını döndür (tüm coinler)."""
        total_connected = 0
        for managers in self._managers.values():
            for mgr in managers.values():
                if mgr.status == ConnectionStatus.BAGLI:
                    total_connected += 1
        return total_connected

    def total_managers(self) -> int:
        return sum(len(m) for m in self._managers.values())

    # ──────────────────────────────────────────────
    # Periyodik coin listesi güncelleme
    # ──────────────────────────────────────────────

    async def auto_update_loop(self) -> None:
        """
        config.yaml'daki interval'e göre periyodik coin listesi güncelleme.
        Binance USDT-perp listesini referans alır.
        """
        interval_hours: float = config.get("coin_update_interval_hours", 24)
        while True:
            await asyncio.sleep(interval_hours * 3600)
            try:
                coins = await _fetch_common_coins()
                await self.update_coin_list(coins)
            except Exception as exc:
                logger.error("Coin listesi otomatik güncelleme hatası: %s", exc)


async def _fetch_common_coins() -> list[str]:
    """
    Binance, Bybit ve OKX'te ortak USDT paritelerini çek.
    min_exchanges_required kadar borsada olan coinleri döndür.
    """
    min_req: int = config.get("min_exchanges_required", 3)

    async with aiohttp.ClientSession() as session:
        binance_coins, bybit_coins, okx_coins = await asyncio.gather(
            _fetch_binance_coins(session),
            _fetch_bybit_coins(session),
            _fetch_okx_coins(session),
        )

    all_coins = set(binance_coins) | set(bybit_coins) | set(okx_coins)
    result = []
    for coin in all_coins:
        count = sum([
            coin in binance_coins,
            coin in bybit_coins,
            coin in okx_coins,
        ])
        if count >= min_req:
            result.append(coin)

    logger.info(
        "Ortak coin listesi: %d coin (%d borsa gereksinimi)",
        len(result), min_req,
    )
    return sorted(result)


async def _fetch_binance_coins(session: aiohttp.ClientSession) -> set[str]:
    try:
        url = "https://api.binance.com/api/v3/exchangeInfo"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()
            return {
                s["symbol"][:-4] + "/USDT"
                for s in data.get("symbols", [])
                if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"
                and s["symbol"].endswith("USDT")
            }
    except Exception as exc:
        logger.error("Binance coin listesi hatası: %s", exc)
        return set()


async def _fetch_bybit_coins(session: aiohttp.ClientSession) -> set[str]:
    try:
        url = "https://api.bybit.com/v5/market/instruments-info?category=spot"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()
            items = data.get("result", {}).get("list", [])
            return {
                item["symbol"][:-4] + "/USDT"
                for item in items
                if item.get("quoteCoin") == "USDT"
                and item.get("status") == "Trading"
                and item["symbol"].endswith("USDT")
            }
    except Exception as exc:
        logger.error("Bybit coin listesi hatası: %s", exc)
        return set()


async def _fetch_okx_coins(session: aiohttp.ClientSession) -> set[str]:
    try:
        url = "https://www.okx.com/api/v5/public/instruments?instType=SPOT"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()
            items = data.get("data", [])
            return {
                item["instId"][:-5] + "/USDT"
                for item in items
                if item.get("quoteCcy") == "USDT"
                and item.get("state") == "live"
                and item["instId"].endswith("-USDT")
            }
    except Exception as exc:
        logger.error("OKX coin listesi hatası: %s", exc)
        return set()
