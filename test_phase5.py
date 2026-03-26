"""
Phase 5 Test — Claude API meta sinyal motoru (mock ile).
Kullanım: python test_phase5.py
"""

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

from src import config
from src.logger_setup import setup_logging
from src.scoring_engine import Signal
from src.meta_signal import MetaSignalEngine, OtherBotSignal, _SYSTEM_PROMPT


def _make_high_score_signal() -> Signal:
    return Signal(
        coin="SOL/USDT",
        level=182.40,
        direction="destek",
        signal_type="S3",
        score=9.1,
        spot_total=3_700_000,
        futures_total=8_500_000,
        exchange_count=3,
        weighted_exchange_score=2.3,
        funding_rate=0.012,
        volume_change_pct=340.0,
        distance_pct=0.31,
        confirming_exchanges=["binance", "bybit", "okx"],
    )


def _make_low_score_signal() -> Signal:
    sig = _make_high_score_signal()
    sig.score = 5.0  # Eşiğin altında
    return sig


def test_should_trigger_conditions() -> None:
    """Meta sinyal tetikleme koşulları doğru çalışıyor mu?"""
    config.load_config()
    engine = MetaSignalEngine()

    high_signal = _make_high_score_signal()
    low_signal = _make_low_score_signal()

    # Diğer bot sinyali olmadan → tetiklenmemeli
    assert not engine.should_trigger(high_signal), "Diğer bot sinyali yokken tetiklenmemeli."

    # Diğer bot sinyali ekle
    bot_signal = OtherBotSignal(
        bot_name="mum_botu",
        data={"pattern": "Hammer", "timeframe": "4H", "dtw_skoru": 0.89},
        timestamp=time.time(),
    )
    engine.register_other_bot_signal("SOL/USDT", bot_signal)

    # Yüksek skor + diğer bot → tetiklenmeli
    assert engine.should_trigger(high_signal), "Yüksek skor ve diğer bot sinyaliyle tetiklenmeli."

    # Düşük skor → tetiklenmemeli
    assert not engine.should_trigger(low_signal), "Düşük skorla tetiklenmemeli."
    print("✅ test_should_trigger_conditions: BAŞARILI")


def test_other_bot_signal_expiry() -> None:
    """Eski diğer bot sinyalleri pencere dışında temizleniyor mu?"""
    config.load_config()
    # Pencere süresini kısa tut (test için)
    config._config["meta_signal_other_bot_window_minutes"] = 0.001  # ~0.06 saniye

    engine = MetaSignalEngine()
    signal = _make_high_score_signal()

    bot_signal = OtherBotSignal(
        bot_name="sr_botu",
        data={"yakin_seviye": 182.10, "guc": "güçlü"},
        timestamp=time.time() - 10,  # 10 saniye önce (pencere dışı)
    )
    engine.register_other_bot_signal("SOL/USDT", bot_signal)

    # Pencere çok kısa, temizlenmiş olmalı
    assert not engine.should_trigger(signal), "Süresi dolmuş sinyal tetiklememeli."

    # Config'i geri yükle
    config._config["meta_signal_other_bot_window_minutes"] = 30
    print("✅ test_other_bot_signal_expiry: BAŞARILI")


def test_payload_building() -> None:
    """Payload metni doğru oluşturuluyor mu?"""
    config.load_config()
    engine = MetaSignalEngine()
    signal = _make_high_score_signal()

    bot_signals = [
        OtherBotSignal(
            bot_name="mum_botu",
            data={"pattern": "Hammer", "timeframe": "4H"},
        ),
        OtherBotSignal(
            bot_name="sr_botu",
            data={"yakin_seviye": 182.10, "guc": "güçlü"},
        ),
    ]

    payload = engine._build_payload(signal, bot_signals)
    assert "SOL/USDT" in payload, "Coin adı payload'da yok."
    assert "182.40" in payload or "182.4" in payload, "Seviye payload'da yok."
    assert "MUM_BOTU" in payload, "Mum botu verisi yok."
    assert "SR_BOTU" in payload, "S/R botu verisi yok."
    assert "Hammer" in payload, "Pattern verisi yok."
    print("✅ test_payload_building: BAŞARILI")


def test_format_telegram_card() -> None:
    """Telegram kart formatı doğru mu?"""
    config.load_config()
    signal = _make_high_score_signal()
    claude_response = (
        "KARAR: GİR-LONG\n"
        "GÜVEN: 8.5/10\n"
        "ÖZET: Üç metodoloji aynı noktayı onaylıyor.\n"
        "GİRİŞ: $182.60 | STOP: $180.10 | HEDEF: $188.50\n"
        "UYARI: Funding nötr, pozisyon hafif tut"
    )

    card = MetaSignalEngine._format_telegram_card(signal, claude_response)
    assert "CLAUDE META SİNYAL" in card, "Başlık eksik."
    assert "SOL/USDT" in card, "Coin adı eksik."
    assert "GİR-LONG" in card, "Karar eksik."
    assert "DESTEK" in card, "Yön eksik."
    print("✅ test_format_telegram_card: BAŞARILI")


def test_system_prompt_content() -> None:
    """System prompt gerekli unsurları içeriyor mu?"""
    assert "KARAR:" in _SYSTEM_PROMPT, "KARAR formatı eksik."
    assert "GÜVEN:" in _SYSTEM_PROMPT, "GÜVEN formatı eksik."
    assert "ÖZET:" in _SYSTEM_PROMPT, "ÖZET formatı eksik."
    assert "GİR-LONG" in _SYSTEM_PROMPT, "GİR-LONG seçeneği eksik."
    assert "BEKLE" in _SYSTEM_PROMPT, "BEKLE seçeneği eksik."
    assert "Türkçe" in _SYSTEM_PROMPT, "Türkçe kuralı eksik."
    print("✅ test_system_prompt_content: BAŞARILI")


def test_generate_with_mock_claude() -> None:
    """Mock Claude API ile generate() çalışıyor mu?"""
    config.load_config()

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=(
        "KARAR: GİR-LONG\n"
        "GÜVEN: 8/10\n"
        "ÖZET: Güçlü sinyal.\n"
        "GİRİŞ: $182.60 | STOP: $180.10 | HEDEF: $188.50\n"
        "UYARI: YOK"
    ))]

    with patch("anthropic.AsyncAnthropic") as mock_anthropic_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_anthropic_cls.return_value = mock_client

        import os
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        try:
            # MetaSignalEngine'i doğrudan mock client ile oluştur
            engine = MetaSignalEngine()
            engine._client = mock_client

            signal = _make_high_score_signal()
            bot_sig = OtherBotSignal(
                bot_name="mum_botu",
                data={"pattern": "Hammer"},
                timestamp=time.time(),
            )
            engine.register_other_bot_signal("SOL/USDT", bot_sig)

            async def run():
                result = await engine.generate(signal)
                return result

            result = asyncio.run(run())
            assert result is not None, "generate() None döndürdü."
            assert "CLAUDE META SİNYAL" in result, "Kart formatı yanlış."
            assert "GİR-LONG" in result, "Claude yanıtı kartta yok."
            print("✅ test_generate_with_mock_claude: BAŞARILI")
        finally:
            del os.environ["ANTHROPIC_API_KEY"]


if __name__ == "__main__":
    setup_logging()
    print("\n=== PHASE 5 TESTLERİ ===\n")
    test_should_trigger_conditions()
    test_other_bot_signal_expiry()
    test_payload_building()
    test_format_telegram_card()
    test_system_prompt_content()
    test_generate_with_mock_claude()
    print("\n✅ Tüm Phase 5 testleri tamamlandı.\n")
