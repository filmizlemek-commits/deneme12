"""
Phase 3 — Telegram Gönderici
python-telegram-bot ile PNG kart ve metin mesajı gönderir.
dry_run modunda terminale yazar, gerçekten göndermez.
"""

import logging
import os
import tempfile

from src import config
from src.scoring_engine import Signal

logger = logging.getLogger(__name__)

# Telegram isteğe bağlı import
try:
    from telegram import Bot
    from telegram.constants import ParseMode
    _TELEGRAM_AVAILABLE = True
except ImportError:
    _TELEGRAM_AVAILABLE = False
    logger.warning("python-telegram-bot yüklü değil. Telegram gönderimi devre dışı.")


class TelegramNotifier:
    """Telegram mesaj ve PNG gönderici."""

    def __init__(self) -> None:
        token = config.get("telegram_token") or os.getenv("TELEGRAM_TOKEN", "")
        self._bot = Bot(token=token) if _TELEGRAM_AVAILABLE and token else None
        self._dry_run = config.is_dry_run()
        self._threads = config.get("telegram_threads", {})

    # ──────────────────────────────────────────────
    # Sinyal gönderme
    # ──────────────────────────────────────────────

    async def send_signal(self, signal: Signal, png_bytes: bytes) -> None:
        """Sinyal kartını uygun thread'e gönder."""
        strong_score: float = config.get("signal_strong_score", 8.0)
        min_score: float = config.get("signal_min_score", 6.0)

        if signal.signal_type == "S4":
            thread_id = self._threads.get("warning", 3)
        elif signal.score >= strong_score:
            thread_id = self._threads.get("strong", 1)
        else:
            thread_id = self._threads.get("normal", 2)

        caption = self._build_signal_caption(signal)
        await self._send_photo(png_bytes, caption, thread_id)

    async def send_meta_signal(self, text: str) -> None:
        """Claude meta sinyal mesajını güçlü sinyaller thread'ine gönder."""
        thread_id = self._threads.get("strong", 1)
        await self._send_text(text, thread_id)

    async def send_system(self, text: str) -> None:
        """Sistem mesajı gönder."""
        thread_id = self._threads.get("system", 4)
        await self._send_text(text, thread_id)

    async def send_warning(self, text: str) -> None:
        """Uyarı mesajı gönder."""
        thread_id = self._threads.get("warning", 3)
        await self._send_text(text, thread_id)

    # ──────────────────────────────────────────────
    # Dahili gönderim metodları
    # ──────────────────────────────────────────────

    async def _send_photo(self, png_bytes: bytes, caption: str, thread_id: int) -> None:
        if self._dry_run:
            logger.info(
                "[DRY-RUN] Telegram'a gönderilecekti (thread %d):\n%s",
                thread_id, caption,
            )
            return

        if not self._bot:
            logger.warning("Telegram bot yapılandırılmamış, mesaj atlandı.")
            return

        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if not chat_id:
            logger.warning("TELEGRAM_CHAT_ID ortam değişkeni eksik.")
            return

        # PNG'yi geçici dosyaya yaz, gönder, sil
        with tempfile.NamedTemporaryFile(
            suffix=".png", dir=tempfile.gettempdir(), delete=False
        ) as tmp:
            tmp.write(png_bytes)
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as f:
                await self._bot.send_photo(
                    chat_id=chat_id,
                    photo=f,
                    caption=caption,
                    message_thread_id=thread_id,
                    parse_mode=ParseMode.HTML,
                )
            logger.info("Sinyal kartı gönderildi (thread %d).", thread_id)
        except Exception as exc:
            logger.error("Telegram fotoğraf gönderme hatası: %s", exc)
        finally:
            os.unlink(tmp_path)

    async def _send_text(self, text: str, thread_id: int) -> None:
        if self._dry_run:
            logger.info(
                "[DRY-RUN] Telegram'a gönderilecekti (thread %d):\n%s",
                thread_id, text,
            )
            return

        if not self._bot:
            return

        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if not chat_id:
            return

        try:
            await self._bot.send_message(
                chat_id=chat_id,
                text=text,
                message_thread_id=thread_id,
                parse_mode=ParseMode.HTML,
            )
        except Exception as exc:
            logger.error("Telegram mesaj gönderme hatası: %s", exc)

    # ──────────────────────────────────────────────
    # Mesaj oluşturucular
    # ──────────────────────────────────────────────

    @staticmethod
    def _build_signal_caption(signal: Signal) -> str:
        direction_emoji = "🟢" if signal.direction == "destek" else "🔴"
        type_labels = {
            "S1": "S1 YAKLAŞIM",
            "S2": "S2 ÇİFT ONAY",
            "S3": "S3 CROSS",
            "S4": "S4 ABSORPSİYON",
        }
        type_str = type_labels.get(signal.signal_type, signal.signal_type)
        ex_str = " | ".join(signal.confirming_exchanges) if signal.confirming_exchanges else "—"

        spot_m = signal.spot_total / 1e6
        futures_m = signal.futures_total / 1e6

        return (
            f"<b>{signal.coin}</b>  {direction_emoji}  <b>{type_str}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 Seviye:   <b>${signal.level:.4f}</b>\n"
            f"📏 Mesafe:   {signal.distance_pct:.2f}%\n"
            f"💰 Spot:     ${spot_m:.2f}M\n"
            f"📈 Vadeli:   ${futures_m:.2f}M\n"
            f"🏦 Borsalar: {ex_str}\n"
            f"⚖️ Ağırlıklı: {signal.weighted_exchange_score:.2f}\n"
            f"💸 Funding:  {signal.funding_rate:+.4f}%\n"
            f"📊 Hacim Δ:  {signal.volume_change_pct:+.1f}%\n"
            f"💪 Skor:     <b>{signal.score:.2f}/10</b>"
        )
