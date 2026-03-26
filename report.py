#!/usr/bin/env python3
"""
Phase 4 — CLI Başarı Raporu
Kullanım: python report.py [--days 7]
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

# Proje kökünü Python path'ine ekle
sys.path.insert(0, str(Path(__file__).parent))

from src import config
from src.db import fetch_recent_signals
from src.logger_setup import setup_logging


def main() -> None:
    setup_logging()
    config.load_config()

    parser = argparse.ArgumentParser(description="Sinyal başarı raporu üret.")
    parser.add_argument("--days", type=int, default=7, help="Kaç günlük veri (varsayılan: 7)")
    args = parser.parse_args()

    signals = fetch_recent_signals(days=args.days)
    if not signals:
        print(f"Son {args.days} günde sinyal kaydı bulunamadı.")
        return

    _print_report(signals, args.days)


def _print_report(signals: list[dict], days: int) -> None:
    total = len(signals)
    print()
    print("=" * 45)
    print("       SİNYAL BAŞARI RAPORU")
    print("=" * 45)
    print(f"Dönem: Son {days} gün  |  Toplam: {total} sinyal")
    print()

    # ── Sinyal türüne göre ──────────────────────────
    print("SINYAL TÜRÜNE GÖRE:")
    by_type: dict[str, list[dict]] = defaultdict(list)
    for sig in signals:
        by_type[sig["sinyal_turu"]].append(sig)

    type_labels = {
        "S1": "S1 YAKLAŞIM  ",
        "S2": "S2 ÇİFT ONAY",
        "S3": "S3 CROSS     ",
        "S4": "S4 ABSORPSİYON",
    }
    for stype in ["S1", "S2", "S3", "S4"]:
        items = by_type.get(stype, [])
        if not items:
            continue
        label = type_labels.get(stype, stype)
        success_rate = _success_rate(items)
        marker = "← en başarılı" if success_rate == max(
            _success_rate(by_type.get(t, [])) for t in ["S1", "S2", "S3", "S4"]
        ) and success_rate > 0 else ""
        print(f"  {label}: {len(items):4d} sinyal — %{success_rate:.0f} tuttu  {marker}")

    print()

    # ── Borsaya göre ────────────────────────────────
    print("BORSAYA GÖRE (onay katkısı):")
    exchanges = ["binance", "bybit", "okx"]
    ex_labels = {"binance": "Binance", "bybit": "Bybit  ", "okx": "OKX    "}

    for ex in exchanges:
        # Bu borsanın katkıda bulunduğu sinyal sayısı (basit: borsa_onay > 0)
        # Gerçek filtreleme için confirming_exchanges alanı gerekirdi; borsa_onay kullanıyoruz
        ex_signals = [s for s in signals if s["borsa_onay"] > 0]
        if not ex_signals:
            continue
        rate = _success_rate(ex_signals)
        label = ex_labels.get(ex, ex)
        print(f"  {label}: {len(ex_signals):4d} katkılı sinyal → %{rate:.0f} tuttu")

    print()

    # ── Skor aralığına göre ─────────────────────────
    print("SKOR ARALIĞINA GÖRE:")
    ranges = [(6.0, 7.0), (7.0, 8.0), (8.0, 11.0)]
    range_labels = {(6.0, 7.0): "6.0–7.0", (7.0, 8.0): "7.0–8.0", (8.0, 11.0): "8.0+   "}
    for low, high in ranges:
        items = [s for s in signals if low <= s["skor"] < high]
        if not items:
            continue
        rate = _success_rate(items)
        label = range_labels[(low, high)]
        print(f"  {label}: %{rate:.0f} başarı  ({len(items)} sinyal)")

    print()

    # ── Öneri ──────────────────────────────────────
    _print_recommendation(signals)
    print("=" * 45)
    print()


def _success_rate(items: list[dict]) -> float:
    """'tuttu' olanların yüzdesi."""
    if not items:
        return 0.0
    tuttu = sum(1 for s in items if s.get("sonuc") == "tuttu")
    evaluated = sum(1 for s in items if s.get("sonuc") in ("tuttu", "tutmadi"))
    if evaluated == 0:
        return 0.0
    return tuttu / evaluated * 100


def _print_recommendation(signals: list[dict]) -> None:
    """Basit öneri üret."""
    current_min = config.get("signal_min_score", 6.0)

    # Skor 7+ sinyallerin başarısı
    high_score_sigs = [s for s in signals if s["skor"] >= 7.0]
    low_score_sigs = [s for s in signals if s["skor"] < 7.0]

    high_rate = _success_rate(high_score_sigs)
    low_rate = _success_rate(low_score_sigs)

    if high_rate > 0 and low_rate > 0 and high_rate - low_rate > 15:
        new_min = min(current_min + 0.5, 8.0)
        print(f"ÖNERİ: signal_min_score {new_min:.1f}'e çıkarılabilir.")
    elif high_rate > 0:
        print("ÖNERİ: Mevcut ayarlar uygun görünüyor.")
    else:
        print("ÖNERİ: Yeterli değerlendirilmiş sinyal yok, daha fazla veri bekleyin.")


if __name__ == "__main__":
    main()
