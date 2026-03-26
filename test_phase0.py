"""
Phase 0 Test — Yapılandırma altyapısı ve DRY_RUN modu.
Kullanım: python test_phase0.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src import config
from src.logger_setup import setup_logging


def test_config_load() -> None:
    """config.yaml başarıyla yükleniyor mu?"""
    cfg = config.load_config()
    assert isinstance(cfg, dict), "Yapılandırma bir sözlük olmalı."
    assert "dry_run" in cfg, "dry_run anahtarı eksik."
    assert "exchange_weights" in cfg, "exchange_weights anahtarı eksik."
    assert "telegram_threads" in cfg, "telegram_threads anahtarı eksik."
    print("✅ test_config_load: BAŞARILI")


def test_get_nested() -> None:
    """Nokta notasyonu ile iç içe anahtar erişimi çalışıyor mu?"""
    config.load_config()
    val = config.get("exchange_weights.binance")
    assert val == 1.0, f"Beklenen 1.0, alınan: {val}"
    val2 = config.get("telegram_threads.strong")
    assert val2 == 1, f"Beklenen 1, alınan: {val2}"
    val3 = config.get("mevcut_degil.anahtar", "varsayilan")
    assert val3 == "varsayilan", f"Beklenen 'varsayilan', alınan: {val3}"
    print("✅ test_get_nested: BAŞARILI")


def test_dry_run() -> None:
    """dry_run modu doğru çalışıyor mu?"""
    config.load_config()
    # config.yaml'da dry_run: true varsayılan
    dr = config.is_dry_run()
    assert isinstance(dr, bool), "dry_run bir bool olmalı."
    print(f"✅ test_dry_run: BAŞARILI (dry_run={dr})")


def test_all_required_keys() -> None:
    """Gerekli tüm anahtarlar var mı?"""
    config.load_config()
    required = [
        "dry_run", "log_language", "exchange_weights",
        "coin_update_interval_hours", "min_exchanges_required",
        "reconnect_max_attempts", "reconnect_wait_seconds",
        "heartbeat_interval_seconds", "orderbook_depth",
        "wall_multiplier", "price_tolerance_pct",
        "confluence_bonus_both", "confluence_bonus_single",
        "exchange_bonus_per_exchange",
        "funding_neutral_bonus", "funding_high_penalty",
        "funding_neutral_max", "funding_high_threshold",
        "volume_spike_bonus", "volume_spike_threshold_pct",
        "signal_min_score", "signal_strong_score",
        "signal_cooldown_minutes", "proximity_threshold_pct",
        "cross_exchange_time_tolerance_sec",
        "ring_buffer_minutes", "ram_target_gb",
        "telegram_token", "telegram_threads",
        "claude_model", "claude_max_tokens",
        "meta_signal_score_threshold", "meta_signal_other_bot_window_minutes",
        "db_path", "health_check_host", "health_check_port",
    ]
    missing = []
    for key in required:
        if config.get(key) is None and config.get(key, "MISSING") == "MISSING":
            missing.append(key)

    if missing:
        print(f"❌ test_all_required_keys: EKSİK ANAHTARLAR: {missing}")
    else:
        print("✅ test_all_required_keys: BAŞARILI")


def test_no_hardcoded_values() -> None:
    """config.yaml default değerleri makul aralıklarda mı?"""
    config.load_config()
    assert 0 < config.get("signal_min_score") <= 10
    assert 0 < config.get("signal_strong_score") <= 10
    assert config.get("signal_strong_score") > config.get("signal_min_score")
    assert config.get("orderbook_depth") > 0
    assert config.get("wall_multiplier") >= 1.0
    print("✅ test_no_hardcoded_values: BAŞARILI")


if __name__ == "__main__":
    setup_logging()
    print("\n=== PHASE 0 TESTLERİ ===\n")
    test_config_load()
    test_get_nested()
    test_dry_run()
    test_all_required_keys()
    test_no_hardcoded_values()
    print("\n✅ Tüm Phase 0 testleri tamamlandı.\n")
