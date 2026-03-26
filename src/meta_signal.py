"""
Phase 5 — Claude API Meta Sinyal Motoru
Diğer botlardan gelen sinyallerle birleştirip meta karar üretir.
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

from src import config
from src.scoring_engine import Signal

logger = logging.getLogger(__name__)

# Anthropic isteğe bağlı import
try:
    import anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False
    logger.warning("anthropic kütüphanesi yüklü değil. Meta sinyal devre dışı.")

_TZ_TR = timezone(timedelta(hours=3))

_SYSTEM_PROMPT = """Sen deneyimli bir kripto trader analistisin.
Bağımsız üç farklı bottan gelen sinyalleri
birleştirerek net karar üret.

Metodolojiler:
- Order Book Botu: Emir defteri duvarları,
  spot+vadeli confluence, cross-exchange onay
- Mum Botu: DTW ile benzer mum formasyonu tespiti
- S/R Botu: Geçmiş destek/direnç seviyeleri

Kurallar:
1. Sinyaller çakışıyorsa güven artar
2. Çelişki varsa açıkla, karar verme "BEKLE" söyle
3. Funding rate yüksekse long sinyalini zorla
4. Asla kesin kazanç vaat etme
5. Maksimum 6 cümle, Türkçe, net

Çıktı formatı (sadece bu yapı):
KARAR: [GİR-LONG / GİR-SHORT / BEKLE / ÇIKIŞ]
GÜVEN: X/10
ÖZET: (2 cümle max)
GİRİŞ: $X | STOP: $X | HEDEF: $X
UYARI: (varsa 1 cümle, yoksa YOK yaz)"""


@dataclass
class OtherBotSignal:
    """Diğer bir bottan gelen sinyal."""
    bot_name: str
    data: dict[str, Any]
    timestamp: float = field(default_factory=lambda: __import__("time").time())


class MetaSignalEngine:
    """
    Claude API'ye bağlanarak meta sinyal üretir.
    Tetiklenme: bu bottan yüksek skor + diğer botlardan son N dk içinde sinyal.
    """

    def __init__(self, telegram_notifier=None) -> None:
        self.telegram_notifier = telegram_notifier
        self._client = None
        if _ANTHROPIC_AVAILABLE:
            api_key = os.getenv("ANTHROPIC_API_KEY", "")
            if api_key:
                self._client = anthropic.AsyncAnthropic(api_key=api_key)
            else:
                logger.warning("ANTHROPIC_API_KEY eksik. Meta sinyal devre dışı.")

        # coin → [OtherBotSignal]
        self._other_bot_signals: dict[str, list[OtherBotSignal]] = {}

    def register_other_bot_signal(self, coin: str, bot_signal: OtherBotSignal) -> None:
        """Diğer bottan gelen sinyali kaydet."""
        if coin not in self._other_bot_signals:
            self._other_bot_signals[coin] = []
        self._other_bot_signals[coin].append(bot_signal)
        self._cleanup_old_signals(coin)

    def _cleanup_old_signals(self, coin: str) -> None:
        """Pencere dışı eski sinyalleri temizle."""
        import time
        window_min: float = config.get("meta_signal_other_bot_window_minutes", 30)
        cutoff = time.time() - window_min * 60
        self._other_bot_signals[coin] = [
            s for s in self._other_bot_signals.get(coin, [])
            if s.timestamp >= cutoff
        ]

    def should_trigger(self, signal: Signal) -> bool:
        """Meta sinyal üretilmeli mi?"""
        threshold: float = config.get("meta_signal_score_threshold", 8.0)
        if signal.score < threshold:
            return False

        self._cleanup_old_signals(signal.coin)
        other_signals = self._other_bot_signals.get(signal.coin, [])
        return len(other_signals) > 0

    async def generate(self, signal: Signal) -> str | None:
        """Claude'a gönder, meta sinyal metni döndür."""
        if not self._client:
            logger.warning("Claude istemcisi hazır değil.")
            return None

        other_signals = self._other_bot_signals.get(signal.coin, [])
        payload = self._build_payload(signal, other_signals)

        try:
            model: str = config.get("claude_model", "claude-sonnet-4-20250514")
            max_tokens: int = config.get("claude_max_tokens", 1000)

            message = await self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=_SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": f"Aşağıdaki sinyal verilerini analiz et:\n\n{payload}",
                    }
                ],
            )
            response_text = message.content[0].text
            logger.info("Claude meta sinyal üretildi: %s", signal.coin)
            return self._format_telegram_card(signal, response_text)

        except Exception as exc:
            logger.error("Claude API hatası: %s", exc)
            return None

    def _build_payload(self, signal: Signal, other_signals: list[OtherBotSignal]) -> str:
        """Claude'a gönderilecek payload metnini oluştur."""
        spot_m = signal.spot_total / 1e6
        futures_m = signal.futures_total / 1e6

        payload_lines = [
            "ORDER BOOK SİNYALİ:",
            f"  Coin: {signal.coin}",
            f"  Seviye: ${signal.level:.4f}",
            f"  Yön: {signal.direction}",
            f"  Skor: {signal.score:.2f}",
            f"  Spot toplam: ${spot_m:.2f}M",
            f"  Vadeli toplam: ${futures_m:.2f}M",
            f"  Borsa onay: {signal.exchange_count}",
            f"  Ağırlıklı borsa skoru: {signal.weighted_exchange_score:.2f}",
            f"  Mesafe: {signal.distance_pct:.2f}%",
            f"  Funding rate: {signal.funding_rate:+.4f}%",
            f"  Hacim değişimi: {signal.volume_change_pct:+.1f}%",
        ]

        for bot_sig in other_signals:
            payload_lines.append(f"\n{bot_sig.bot_name.upper()} SİNYALİ:")
            for k, v in bot_sig.data.items():
                payload_lines.append(f"  {k}: {v}")

        return "\n".join(payload_lines)

    @staticmethod
    def _format_telegram_card(signal: Signal, claude_response: str) -> str:
        """Claude yanıtından Telegram kartı oluştur."""
        now_tr = datetime.now(_TZ_TR).strftime("%H:%M:%S")
        direction_str = "DESTEK" if signal.direction == "destek" else "DİRENÇ"

        return (
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🧠 CLAUDE META SİNYAL\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 {signal.coin} — {direction_str} ${signal.level:.4f}\n\n"
            f"{claude_response}\n\n"
            "📊 Kaynak Sinyaller:\n"
            f"• Order Book: {signal.score:.1f}/10  ✅\n"
            f"\n⏱ {now_tr}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

    async def process_signal(self, signal: Signal) -> None:
        """Koşullar sağlanıyorsa meta sinyal üret ve Telegram'a gönder."""
        if not self.should_trigger(signal):
            return

        meta_text = await self.generate(signal)
        if meta_text and self.telegram_notifier:
            await self.telegram_notifier.send_meta_signal(meta_text)
