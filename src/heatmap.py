"""
Phase 3 — Isı Haritası ve Telegram Kartı
matplotlib ile PNG görsel üretimi.
"""

import io
import logging
import time
from datetime import datetime, timezone, timedelta

import matplotlib
matplotlib.use("Agg")  # GUI gerektirmez
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np

from src import config
from src.scoring_engine import Signal
from src.ring_buffer import RingBufferManager

logger = logging.getLogger(__name__)

# UTC+3 (Türkiye)
_TZ_TR = timezone(timedelta(hours=3))


def generate_signal_card(
    signal: Signal,
    buffer: RingBufferManager,
) -> bytes:
    """
    Sinyal için PNG görsel üretir.
    3 panel: ısı haritası, spot vs vadeli karşılaştırma, alt bilgi şeridi.
    Bytes olarak döndürür.
    """
    buf = buffer.get_buffer(signal.coin)

    # Arka plan rengi
    if signal.signal_type == "S4":
        bg_color = "#3d3000"   # Sarı kart (absorpsiyon)
        accent = "#FFD700"
    elif signal.direction == "destek":
        bg_color = "#0a2000"   # Yeşil kart
        accent = "#00C853"
    else:
        bg_color = "#200000"   # Kırmızı kart
        accent = "#F44336"

    fig = plt.figure(figsize=(10, 8), facecolor=bg_color)
    gs = gridspec.GridSpec(
        3, 1,
        height_ratios=[3, 2, 1],
        hspace=0.35,
        left=0.08, right=0.95, top=0.93, bottom=0.05,
    )

    ax_heat = fig.add_subplot(gs[0])
    ax_bar = fig.add_subplot(gs[1])
    ax_info = fig.add_subplot(gs[2])

    for ax in [ax_heat, ax_bar, ax_info]:
        ax.set_facecolor(bg_color)
        for spine in ax.spines.values():
            spine.set_edgecolor(accent)

    # ── ÜST PANEL: Isı haritası ──────────────────────────────
    _draw_heatmap(ax_heat, signal, buf, bg_color, accent)

    # ── ORTA PANEL: Spot vs Vadeli çubuk grafik ──────────────
    _draw_bar_chart(ax_bar, signal, buf, bg_color, accent)

    # ── ALT ŞERİT: Bilgi özeti ───────────────────────────────
    _draw_info_strip(ax_info, signal, bg_color, accent)

    # Başlık
    now_tr = datetime.now(_TZ_TR).strftime("%H:%M:%S")
    direction_str = "🟢 DESTEK" if signal.direction == "destek" else "🔴 DİRENÇ"
    fig.suptitle(
        f"{signal.coin}  |  {direction_str}  |  {signal.signal_type}  |  {now_tr}",
        color=accent,
        fontsize=14,
        fontweight="bold",
    )

    # PNG olarak kaydet
    buf_io = io.BytesIO()
    fig.savefig(buf_io, format="png", facecolor=bg_color, dpi=120)
    plt.close(fig)
    buf_io.seek(0)
    return buf_io.read()


# ──────────────────────────────────────────────────────────────
# Panel çiziciler
# ──────────────────────────────────────────────────────────────

def _draw_heatmap(ax, signal: Signal, buf, bg_color: str, accent: str) -> None:
    """Isı haritası paneli."""
    ax.set_title("ISI HARİTASI (Son 30dk)", color=accent, fontsize=10, pad=4)

    if buf is None or not buf.snapshots:
        ax.text(0.5, 0.5, "Veri yok", ha="center", va="center",
                color="gray", transform=ax.transAxes)
        return

    current_price = buf.last_price
    price_range = current_price * 0.02  # ±%2
    price_min = current_price - price_range
    price_max = current_price + price_range

    # Zaman dilimlerine göre snapshot'ları grupla (5dk aralıklı)
    now = time.time()
    time_slots = [now - i * 5 * 60 for i in range(6, -1, -1)]  # 7 slot
    n_price_bins = 40
    price_bins = np.linspace(price_min, price_max, n_price_bins)
    heatmap_data = np.zeros((n_price_bins - 1, len(time_slots) - 1))

    for snap in buf.snapshots:
        # Zaman slotu bul
        t_idx = None
        for i in range(len(time_slots) - 1):
            if time_slots[i] <= snap.timestamp < time_slots[i + 1]:
                t_idx = i
                break
        if t_idx is None:
            continue

        for arr in [snap.bids, snap.asks]:
            if arr is None or len(arr) == 0:
                continue
            prices = arr[:, 0]
            sizes = arr[:, 1] * prices  # USD

            for price, usd_size in zip(prices, sizes):
                if price_min <= price <= price_max:
                    p_idx = int((price - price_min) / (price_max - price_min) * (n_price_bins - 1))
                    p_idx = max(0, min(p_idx, n_price_bins - 2))
                    heatmap_data[p_idx, t_idx] += usd_size

    if heatmap_data.max() > 0:
        heatmap_data = np.log1p(heatmap_data)

    time_labels = [
        datetime.fromtimestamp(t, tz=_TZ_TR).strftime("%H:%M")
        for t in time_slots[:-1]
    ]

    im = ax.imshow(
        heatmap_data.T,
        aspect="auto",
        origin="lower",
        cmap="hot",
        interpolation="bilinear",
    )

    ax.set_xticks(range(len(time_labels)))
    ax.set_xticklabels(time_labels, color="white", fontsize=7)

    # Y ekseni fiyat etiketleri
    n_yticks = 5
    y_tick_positions = np.linspace(0, n_price_bins - 2, n_yticks)
    y_tick_labels = [
        f"${price_bins[int(p)]:.2f}" for p in y_tick_positions
    ]
    ax.set_yticks(y_tick_positions)
    ax.set_yticklabels(y_tick_labels, color="white", fontsize=7)

    # Mevcut fiyat çizgisi
    current_y = (current_price - price_min) / (price_max - price_min) * (n_price_bins - 2)
    ax.axhline(y=current_y, color="white", linewidth=1.5, linestyle="--", alpha=0.8)

    # Sinyal seviyesi
    level_y = (signal.level - price_min) / (price_max - price_min) * (n_price_bins - 2)
    ax.axhline(y=level_y, color=accent, linewidth=2, linestyle="-", alpha=0.9)
    ax.text(
        len(time_labels) - 0.5, level_y,
        f"${signal.level:.2f}",
        color=accent, fontsize=8, va="center",
    )


def _draw_bar_chart(ax, signal: Signal, buf, bg_color: str, accent: str) -> None:
    """Spot vs Vadeli çubuk grafik."""
    ax.set_title("SPOT vs VADELİ DUVAR (Borsalara Göre)", color=accent, fontsize=10, pad=4)

    exchange_weights = config.get("exchange_weights", {"binance": 1.0, "bybit": 0.7, "okx": 0.6})
    exchanges = ["Binance", "Bybit", "OKX"]
    ex_keys = ["binance", "bybit", "okx"]

    if buf is None or not buf.snapshots:
        ax.text(0.5, 0.5, "Veri yok", ha="center", va="center",
                color="gray", transform=ax.transAxes)
        return

    spot_vals = []
    futures_vals = []
    for ex in ex_keys:
        weight = exchange_weights.get(ex, 0.5)
        snap_spot = buf.latest_snapshot(ex, "spot")
        snap_fut = buf.latest_snapshot(ex, "futures")

        spot_wall = 0.0
        if snap_spot is not None and len(snap_spot.bids) > 0:
            prices = snap_spot.bids[:, 0]
            sizes = snap_spot.bids[:, 1]
            spot_wall = float(np.sum(prices * sizes)) / 1e6 * weight

        futures_wall = 0.0
        if snap_fut is not None and len(snap_fut.bids) > 0:
            prices = snap_fut.bids[:, 0]
            sizes = snap_fut.bids[:, 1]
            futures_wall = float(np.sum(prices * sizes)) / 1e6 * weight

        spot_vals.append(spot_wall)
        futures_vals.append(futures_wall)

    y = np.arange(len(exchanges))
    height = 0.35

    bars_spot = ax.barh(y + height / 2, spot_vals, height, label="Spot", color="#2196F3", alpha=0.8)
    bars_fut = ax.barh(y - height / 2, futures_vals, height, label="Vadeli", color="#FF9800", alpha=0.8)

    ax.set_yticks(y)
    ax.set_yticklabels(exchanges, color="white", fontsize=9)
    ax.tick_params(axis="x", colors="white", labelsize=7)
    ax.set_xlabel("Ağırlıklı Hacim ($M)", color="white", fontsize=8)
    ax.legend(fontsize=8, labelcolor="white", facecolor=bg_color, edgecolor=accent)

    for bar in bars_spot:
        w = bar.get_width()
        if w > 0:
            ax.text(w, bar.get_y() + bar.get_height() / 2, f"{w:.2f}M",
                    va="center", color="white", fontsize=7)
    for bar in bars_fut:
        w = bar.get_width()
        if w > 0:
            ax.text(w, bar.get_y() + bar.get_height() / 2, f"{w:.2f}M",
                    va="center", color="white", fontsize=7)


def _draw_info_strip(ax, signal: Signal, bg_color: str, accent: str) -> None:
    """Alt bilgi şeridi."""
    ax.axis("off")

    now_tr = datetime.now(_TZ_TR).strftime("%Y-%m-%d %H:%M:%S")
    direction_emoji = "🟢" if signal.direction == "destek" else "🔴"
    ex_str = " | ".join(signal.confirming_exchanges) if signal.confirming_exchanges else "—"

    funding_str = f"{signal.funding_rate:+.4f}%"
    volume_str = f"{signal.volume_change_pct:+.1f}%"
    distance_str = f"{signal.distance_pct:.2f}%"

    line1 = (
        f"{direction_emoji} {signal.coin}  |  Seviye: ${signal.level:.4f}  |  "
        f"Mesafe: {distance_str}  |  {signal.signal_type}"
    )
    line2 = (
        f"Borsalar: {ex_str}  |  Ağırlıklı: {signal.weighted_exchange_score:.2f}  |  "
        f"Funding: {funding_str}  |  Hacim Δ: {volume_str}"
    )
    line3 = f"💪 GÜÇ SKORU: {signal.score:.2f}/10  |  🕐 {now_tr}"

    ax.text(0.5, 0.80, line1, ha="center", va="center", color="white",
            fontsize=8.5, transform=ax.transAxes)
    ax.text(0.5, 0.50, line2, ha="center", va="center", color="white",
            fontsize=8, transform=ax.transAxes)
    ax.text(0.5, 0.15, line3, ha="center", va="center", color=accent,
            fontsize=10, fontweight="bold", transform=ax.transAxes)
