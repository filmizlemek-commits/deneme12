"""
Phase 4 Test — SQLite sinyal logu ve CLI rapor.
Kullanım: python test_phase4.py
"""

import os
import sys
import time
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src import config
from src.logger_setup import setup_logging
from src.scoring_engine import Signal
from src.db import init_db, save_signal, update_result, fetch_recent_signals


def _make_test_signal(score: float = 7.5, signal_type: str = "S2") -> Signal:
    return Signal(
        coin="BTC/USDT",
        level=50000.0,
        direction="destek",
        signal_type=signal_type,
        score=score,
        spot_total=1_000_000,
        futures_total=2_000_000,
        exchange_count=3,
        weighted_exchange_score=2.3,
        funding_rate=0.01,
        volume_change_pct=150.0,
        distance_pct=0.3,
        confirming_exchanges=["binance", "bybit", "okx"],
    )


def _setup_test_db() -> str:
    """Geçici test veritabanı oluştur."""
    tmp = tempfile.mktemp(suffix=".db", prefix="test_signals_")
    # config'i test DB yolunu kullanacak şekilde güncelle
    config._config["db_path"] = tmp
    init_db()
    return tmp


def test_init_db() -> None:
    """Veritabanı başlatma çalışıyor mu?"""
    config.load_config()
    tmp_db = _setup_test_db()
    try:
        import sqlite3
        with sqlite3.connect(tmp_db) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = [t[0] for t in tables]
            assert "signals" in table_names, "signals tablosu oluşturulmadı."
        print("✅ test_init_db: BAŞARILI")
    finally:
        os.unlink(tmp_db)


def test_save_signal() -> None:
    """Sinyal kaydı doğru çalışıyor mu?"""
    config.load_config()
    tmp_db = _setup_test_db()
    try:
        signal = _make_test_signal(score=8.2, signal_type="S3")
        row_id = save_signal(signal)
        assert row_id > 0, f"Geçersiz row ID: {row_id}"

        import sqlite3
        with sqlite3.connect(tmp_db) as conn:
            row = conn.execute(
                "SELECT * FROM signals WHERE id = ?", (row_id,)
            ).fetchone()
            assert row is not None, "Kayıt bulunamadı."
            assert row[1] == "BTC/USDT", f"Coin adı yanlış: {row[1]}"
            assert abs(row[2] - 50000.0) < 0.01, f"Seviye yanlış: {row[2]}"
            assert abs(row[3] - 8.2) < 0.01, f"Skor yanlış: {row[3]}"
            assert row[4] == "S3", f"Sinyal türü yanlış: {row[4]}"
            assert row[12] == "bekliyor", f"Sonuç varsayılanı yanlış: {row[12]}"
        print("✅ test_save_signal: BAŞARILI")
    finally:
        os.unlink(tmp_db)


def test_update_result() -> None:
    """Sinyal sonucu güncellenebiliyor mu?"""
    config.load_config()
    tmp_db = _setup_test_db()
    try:
        signal = _make_test_signal()
        row_id = save_signal(signal)
        update_result(row_id, "tuttu")

        import sqlite3
        with sqlite3.connect(tmp_db) as conn:
            sonuc = conn.execute(
                "SELECT sonuc FROM signals WHERE id = ?", (row_id,)
            ).fetchone()[0]
            assert sonuc == "tuttu", f"Sonuç güncellenemedi: {sonuc}"
        print("✅ test_update_result: BAŞARILI")
    finally:
        os.unlink(tmp_db)


def test_fetch_recent_signals() -> None:
    """Son N günün sinyalleri doğru getiriliyor mu?"""
    config.load_config()
    tmp_db = _setup_test_db()
    try:
        # 5 sinyal kaydet
        for i in range(5):
            sig = _make_test_signal(score=6.0 + i * 0.5)
            save_signal(sig)

        signals = fetch_recent_signals(days=7)
        assert len(signals) == 5, f"Beklenen 5, alınan: {len(signals)}"
        assert all("coin" in s for s in signals), "coin anahtarı eksik."
        assert all("skor" in s for s in signals), "skor anahtarı eksik."
        print("✅ test_fetch_recent_signals: BAŞARILI")
    finally:
        os.unlink(tmp_db)


def test_multiple_signal_types() -> None:
    """Farklı sinyal türleri kaydedilebiliyor mu?"""
    config.load_config()
    tmp_db = _setup_test_db()
    try:
        for stype in ["S1", "S2", "S3", "S4"]:
            sig = _make_test_signal(signal_type=stype)
            save_signal(sig)

        signals = fetch_recent_signals(days=7)
        types = {s["sinyal_turu"] for s in signals}
        assert types == {"S1", "S2", "S3", "S4"}, f"Eksik türler: {types}"
        print("✅ test_multiple_signal_types: BAŞARILI")
    finally:
        os.unlink(tmp_db)


def test_report_no_crash() -> None:
    """report.py çalıştırılabilir ve hata vermiyor mu?"""
    config.load_config()
    tmp_db = _setup_test_db()
    try:
        # Birkaç sinyal kaydet
        for i, stype in enumerate(["S1", "S2", "S2", "S3"]):
            sig = _make_test_signal(score=6.0 + i, signal_type=stype)
            row_id = save_signal(sig)
            if i % 2 == 0:
                update_result(row_id, "tuttu")
            else:
                update_result(row_id, "tutmadi")

        # report modülünü import edip test et
        from report import _print_report
        signals = fetch_recent_signals(days=7)
        _print_report(signals, days=7)
        print("✅ test_report_no_crash: BAŞARILI")
    finally:
        os.unlink(tmp_db)


if __name__ == "__main__":
    setup_logging()
    print("\n=== PHASE 4 TESTLERİ ===\n")
    test_init_db()
    test_save_signal()
    test_update_result()
    test_fetch_recent_signals()
    test_multiple_signal_types()
    test_report_no_crash()
    print("\n✅ Tüm Phase 4 testleri tamamlandı.\n")
