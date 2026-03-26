"""
Phase 2 — Skorlama Motoru
Emir defteri verilerinden duvar tespiti, sinyal üretimi ve skorlama.
"""

import logging
import math
import time
from dataclasses import dataclass, field

import numpy as np

from src import config
from src.ring_buffer import RingBufferManager, OrderBookSnapshot

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Veri yapıları
# ──────────────────────────────────────────────────────────────

@dataclass
class WallLevel:
    """Tespit edilen bir emir duvarı."""
    price: float
    size: float               # USD hacmi
    side: str                 # "bid" | "ask"
    exchange: str
    market_type: str          # "spot" | "futures"
    timestamp: float          # Anlık görüntü zamanı (UTC)
    book_avg_size: float = 0.0  # Tüm emir defterinin ortalama USD hacmi (oran hesabı için)


@dataclass
class Signal:
    """Üretilen sinyal."""
    coin: str
    level: float
    direction: str            # "destek" | "direnc"
    signal_type: str          # "S1" | "S2" | "S3" | "S4"
    score: float
    spot_total: float
    futures_total: float
    exchange_count: int
    weighted_exchange_score: float
    funding_rate: float
    volume_change_pct: float
    distance_pct: float
    timestamp: float = field(default_factory=time.time)
    confirming_exchanges: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────
# Yardımcı fonksiyonlar
# ──────────────────────────────────────────────────────────────

def _compute_wall_threshold(sizes: np.ndarray, multiplier: float) -> float:
    """Duvar eşiğini hesapla: ortalama × çarpan."""
    if len(sizes) == 0:
        return 0.0
    return float(np.mean(sizes)) * multiplier


def _find_walls(snapshot: OrderBookSnapshot, multiplier: float) -> list[WallLevel]:
    """Bir anlık görüntüdeki duvarları tespit et."""
    walls: list[WallLevel] = []

    for side, arr in [("bid", snapshot.bids), ("ask", snapshot.asks)]:
        if arr is None or len(arr) == 0:
            continue
        prices = arr[:, 0]
        sizes = arr[:, 1]
        # USD hacmi = fiyat × miktar
        usd_sizes = prices * sizes
        threshold = _compute_wall_threshold(usd_sizes, multiplier)
        if threshold == 0:
            continue
        book_avg = float(np.mean(usd_sizes))
        for price, usd_size in zip(prices, usd_sizes):
            if usd_size >= threshold:
                walls.append(
                    WallLevel(
                        price=float(price),
                        size=float(usd_size),
                        side=side,
                        exchange=snapshot.exchange,
                        market_type=snapshot.market_type,
                        timestamp=snapshot.timestamp,
                        book_avg_size=book_avg,
                    )
                )
    return walls


def _are_same_level(price_a: float, price_b: float, tolerance_pct: float) -> bool:
    """İki fiyat seviyesi aynı mı? (tolerans kontrolü)."""
    if price_a == 0:
        return False
    return abs(price_a - price_b) / price_a * 100 <= tolerance_pct


# ──────────────────────────────────────────────────────────────
# Ana skorlama motoru
# ──────────────────────────────────────────────────────────────

class ScoringEngine:
    """Her 5 dakikada bir tüm coin listesini tarar ve sinyal üretir."""

    def __init__(self, buffer: RingBufferManager) -> None:
        self.buffer = buffer
        # coin → son sinyal zamanı (cooldown için)
        self._last_signal_times: dict[str, float] = {}

    def scan_all(self) -> list[Signal]:
        """Tüm coinleri tara, skor üreten sinyalleri döndür."""
        signals: list[Signal] = []
        for coin in self.buffer.coins():
            coin_signals = self._scan_coin(coin)
            signals.extend(coin_signals)

        # Skora göre sırala (en yüksek önce)
        signals.sort(key=lambda s: s.score, reverse=True)
        # En fazla 20 sinyal
        return signals[:20]

    def _scan_coin(self, coin: str) -> list[Signal]:
        """Tek bir coini tara."""
        buf = self.buffer.get_buffer(coin)
        if buf is None or not buf.snapshots:
            return []

        current_price = buf.last_price
        if current_price <= 0:
            return []

        # Cooldown kontrolü
        cooldown_min: float = config.get("signal_cooldown_minutes", 30)
        last_time = self._last_signal_times.get(coin, 0)
        if time.time() - last_time < cooldown_min * 60:
            return []

        # Tüm anlık görüntülerden duvarları topla
        wall_multiplier: float = config.get("wall_multiplier", 3.0)
        all_walls: list[WallLevel] = []
        for snap in buf.snapshots:
            all_walls.extend(_find_walls(snap, wall_multiplier))

        if not all_walls:
            return []

        # Seviyeleri grupla
        grouped = self._group_walls_by_level(all_walls)
        signals: list[Signal] = []

        min_score: float = config.get("signal_min_score", 6.0)
        proximity_pct: float = config.get("proximity_threshold_pct", 0.5)

        for level_price, level_walls in grouped.items():
            distance_pct = abs(current_price - level_price) / current_price * 100

            # Sinyal türünü belirle
            signal_type, direction = self._determine_signal_type(
                level_price, level_walls, current_price, distance_pct
            )
            if signal_type is None:
                continue

            # Skoru hesapla
            score = self._compute_score(
                coin=coin,
                level_price=level_price,
                level_walls=level_walls,
                current_price=current_price,
                distance_pct=distance_pct,
                buf=buf,
            )

            if score < min_score:
                continue

            # Onaylayan borsalar
            confirming = list({w.exchange for w in level_walls})
            spot_total = sum(w.size for w in level_walls if w.market_type == "spot")
            futures_total = sum(w.size for w in level_walls if w.market_type == "futures")
            exchange_weights = config.get("exchange_weights", {})
            weighted_score = sum(
                exchange_weights.get(ex, 0.5)
                for ex in confirming
            )

            sig = Signal(
                coin=coin,
                level=level_price,
                direction=direction,
                signal_type=signal_type,
                score=min(score, 10.0),
                spot_total=spot_total,
                futures_total=futures_total,
                exchange_count=len(confirming),
                weighted_exchange_score=weighted_score,
                funding_rate=buf.funding_rate,
                volume_change_pct=buf.volume_change_pct,
                distance_pct=distance_pct,
                confirming_exchanges=confirming,
            )
            signals.append(sig)
            self._last_signal_times[coin] = time.time()

        return signals

    def _group_walls_by_level(
        self,
        walls: list[WallLevel],
    ) -> dict[float, list[WallLevel]]:
        """Yakın seviyeleri grupla."""
        tolerance_pct: float = config.get("price_tolerance_pct", 0.2)
        groups: dict[float, list[WallLevel]] = {}

        for wall in walls:
            matched = False
            for key in groups:
                if _are_same_level(wall.price, key, tolerance_pct):
                    groups[key].append(wall)
                    matched = True
                    break
            if not matched:
                groups[wall.price] = [wall]

        return groups

    def _determine_signal_type(
        self,
        level_price: float,
        walls: list[WallLevel],
        current_price: float,
        distance_pct: float,
    ) -> tuple[str | None, str]:
        """Sinyal türünü ve yönünü belirle."""
        tolerance: float = config.get("cross_exchange_time_tolerance_sec", 2)
        proximity_pct: float = config.get("proximity_threshold_pct", 0.5)

        # Yön: bid duvarı → destek, ask duvarı → direnç
        sides = [w.side for w in walls]
        bid_count = sides.count("bid")
        ask_count = sides.count("ask")
        direction = "destek" if bid_count >= ask_count else "direnc"

        # Onaylayan borsalar
        exchanges = list({w.exchange for w in walls})
        market_types = list({w.market_type for w in walls})
        has_spot = "spot" in market_types
        has_futures = "futures" in market_types

        # Absorpsiyon tespiti: büyük bir duvar son 5 dakikada yok oldu mu?
        # (Basit kural: eski snapshot'ta var, yenisinde yok)
        is_absorbed = self._check_absorption(walls)
        if is_absorbed:
            return "S4", direction

        # Cross-exchange: 2+ borsada eş zamanlı duvar
        if len(exchanges) >= 2:
            # Zaman senkronizasyonu kontrolü
            timestamps = [w.timestamp for w in walls]
            if max(timestamps) - min(timestamps) <= tolerance:
                return "S3", direction

        # Çift onay: spot VE vadeli aynı seviye
        if has_spot and has_futures:
            return "S2", direction

        # Yaklaşım: fiyat duvarın yakınında
        if distance_pct <= proximity_pct:
            return "S1", direction

        return None, direction

    def _check_absorption(self, walls: list[WallLevel]) -> bool:
        """
        Büyük duvarın son 5 dakikada absorbe edilip edilmediğini kontrol et.
        Basit kural: Duvarın en eski ve en yeni kaydı arasında %50+ hacim düşüşü.
        """
        if len(walls) < 2:
            return False
        sorted_walls = sorted(walls, key=lambda w: w.timestamp)
        oldest = sorted_walls[0]
        newest = sorted_walls[-1]
        if newest.timestamp - oldest.timestamp < 60:  # En az 1 dakika
            return False
        if oldest.size > 0 and newest.size < oldest.size * 0.5:
            return True
        return False

    def _compute_score(
        self,
        coin: str,
        level_price: float,
        level_walls: list[WallLevel],
        current_price: float,
        distance_pct: float,
        buf,
    ) -> float:
        """Skor formülünü uygula."""
        # Yapılandırma değerleri
        confluence_both: float = config.get("confluence_bonus_both", 1.5)
        confluence_single: float = config.get("confluence_bonus_single", 1.0)
        ex_bonus_per: float = config.get("exchange_bonus_per_exchange", 0.3)
        funding_neutral_bonus: float = config.get("funding_neutral_bonus", 0.2)
        funding_high_penalty: float = config.get("funding_high_penalty", 0.3)
        funding_neutral_max: float = config.get("funding_neutral_max", 0.05)
        funding_high_threshold: float = config.get("funding_high_threshold", 0.1)
        volume_spike_bonus: float = config.get("volume_spike_bonus", 0.2)
        volume_spike_pct: float = config.get("volume_spike_threshold_pct", 200)
        exchange_weights: dict = config.get("exchange_weights", {})

        # Proximity score: 1 - mesafe/seviye (max 2 ile normalize)
        proximity_score = max(0.0, 1.0 - distance_pct / 2.0)

        # Wall score: duvar hacmi / ortalama emir defteri hacmi
        # book_avg_size: tüm emir defterinin ortalama USD hacmi (duvarın ne kadar baskın olduğunu gösterir)
        book_avgs = [w.book_avg_size for w in level_walls if w.book_avg_size > 0]
        book_avg = float(np.mean(book_avgs)) if book_avgs else 1.0
        wall_total = float(np.sum([w.size for w in level_walls]))
        # Birden fazla snapshot'tan gelebileceği için grup boyutuna böl
        n_unique = max(len({(w.exchange, w.market_type) for w in level_walls}), 1)
        wall_score = (wall_total / n_unique) / max(book_avg, 1)
        wall_score = min(wall_score, 10.0)  # Cap

        # Confluence bonus
        market_types = {w.market_type for w in level_walls}
        if "spot" in market_types and "futures" in market_types:
            confluence_bonus = confluence_both
        else:
            confluence_bonus = confluence_single

        # Ağırlıklı exchange bonus
        confirming_exchanges = list({w.exchange for w in level_walls})
        exchange_bonus = sum(
            exchange_weights.get(ex, 0.5) for ex in confirming_exchanges
        ) * ex_bonus_per

        # Funding bonus/ceza
        funding = abs(buf.funding_rate)
        sides = [w.side for w in level_walls]
        is_bid_wall = sides.count("bid") >= len(sides) / 2
        if funding <= funding_neutral_max:
            funding_adj = funding_neutral_bonus
        elif funding >= funding_high_threshold and is_bid_wall:
            funding_adj = -funding_high_penalty
        else:
            funding_adj = 0.0

        # Hacim bonusu
        volume_adj = volume_spike_bonus if buf.volume_change_pct >= volume_spike_pct else 0.0

        # Final skor: base'i 10'a normalize et, bonusları ekle
        # base: proximity(0-1) × wall_score(0-10) × confluence(1.0-1.5) → max ~15
        # Logaritmik ölçekleme: log(1+base)/log(1+10) * 8.0 + bonuslar (max 2.0)
        base = proximity_score * wall_score * confluence_bonus
        base_norm = math.log1p(base) / math.log1p(10.0) * 8.0
        final = base_norm + exchange_bonus + funding_adj + volume_adj

        # 0-10 normalize
        return max(0.0, min(10.0, final))
