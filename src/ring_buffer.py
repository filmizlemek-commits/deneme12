"""
Phase 1 — Veri Toplayıcı
Ring buffer: Her coin için son N dakika emir defteri anlık görüntülerini
RAM'de numpy dizileri olarak tutar.
"""

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque

import numpy as np

from src import config

logger = logging.getLogger(__name__)


@dataclass
class OrderBookSnapshot:
    """Tek bir emir defteri anlık görüntüsü."""
    timestamp: float          # Unix time (UTC)
    bids: np.ndarray          # shape: (N, 2) — [fiyat, miktar]
    asks: np.ndarray          # shape: (N, 2) — [fiyat, miktar]
    exchange: str             # "binance" | "bybit" | "okx"
    market_type: str          # "spot" | "futures"


@dataclass
class CoinBuffer:
    """Tek bir coin için ring buffer."""
    coin: str
    snapshots: Deque[OrderBookSnapshot] = field(default_factory=deque)
    funding_rate: float = 0.0
    volume_change_pct: float = 0.0
    atr: float = 0.0
    last_price: float = 0.0
    last_updated: float = 0.0

    def add_snapshot(self, snapshot: OrderBookSnapshot) -> None:
        """Anlık görüntü ekle ve eski verileri temizle."""
        self.snapshots.append(snapshot)
        self._evict_old()

    def _evict_old(self) -> None:
        """Ring buffer sınırını aşan eski anlık görüntüleri temizle."""
        minutes: int = config.get("ring_buffer_minutes", 30)
        cutoff = time.time() - minutes * 60
        while self.snapshots and self.snapshots[0].timestamp < cutoff:
            self.snapshots.popleft()

    def latest_snapshot(
        self, exchange: str, market_type: str
    ) -> OrderBookSnapshot | None:
        """Belirli borsa/tip için en son anlık görüntüyü döndür."""
        for snap in reversed(self.snapshots):
            if snap.exchange == exchange and snap.market_type == market_type:
                return snap
        return None

    def estimate_ram_bytes(self) -> int:
        """Yaklaşık RAM kullanımını byte cinsinden tahmin et."""
        total = 0
        for snap in self.snapshots:
            total += snap.bids.nbytes + snap.asks.nbytes
        return total


class RingBufferManager:
    """Tüm coinlerin ring buffer'larını yönetir."""

    def __init__(self) -> None:
        self._buffers: dict[str, CoinBuffer] = {}

    def get_or_create(self, coin: str) -> CoinBuffer:
        if coin not in self._buffers:
            self._buffers[coin] = CoinBuffer(coin=coin)
        return self._buffers[coin]

    def remove_coin(self, coin: str) -> None:
        """Çıkan coin için buffer'ı temizle."""
        if coin in self._buffers:
            del self._buffers[coin]
            logger.info("Ring buffer temizlendi: %s", coin)

    def add_snapshot(
        self,
        coin: str,
        exchange: str,
        market_type: str,
        bids: list[list[float]],
        asks: list[list[float]],
    ) -> None:
        """Emir defteri verisini buffer'a ekle."""
        buf = self.get_or_create(coin)
        snap = OrderBookSnapshot(
            timestamp=time.time(),
            bids=np.array(bids, dtype=np.float64),
            asks=np.array(asks, dtype=np.float64),
            exchange=exchange,
            market_type=market_type,
        )
        buf.add_snapshot(snap)

    def update_extras(
        self,
        coin: str,
        funding_rate: float | None = None,
        volume_change_pct: float | None = None,
        atr: float | None = None,
        last_price: float | None = None,
    ) -> None:
        """Ek verileri güncelle (funding, hacim, ATR, fiyat)."""
        buf = self.get_or_create(coin)
        if funding_rate is not None:
            buf.funding_rate = funding_rate
        if volume_change_pct is not None:
            buf.volume_change_pct = volume_change_pct
        if atr is not None:
            buf.atr = atr
        if last_price is not None:
            buf.last_price = last_price
        buf.last_updated = time.time()

    def total_ram_mb(self) -> float:
        """Toplam tahmini RAM kullanımını MB cinsinden döndür."""
        total_bytes = sum(b.estimate_ram_bytes() for b in self._buffers.values())
        return total_bytes / (1024 * 1024)

    def coins(self) -> list[str]:
        return list(self._buffers.keys())

    def get_buffer(self, coin: str) -> CoinBuffer | None:
        return self._buffers.get(coin)
