"""
Ana orkestratör — Tüm phase'leri bir arada çalıştırır.
Kullanım: python main.py
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Proje kökünü path'e ekle
sys.path.insert(0, str(Path(__file__).parent))

from src import config
from src.logger_setup import setup_logging
from src.ring_buffer import RingBufferManager
from src.coin_supervisor import CoinSupervisor
from src.scoring_engine import ScoringEngine
from src.telegram_notifier import TelegramNotifier
from src.heatmap import generate_signal_card
from src.db import init_db, save_signal
from src.meta_signal import MetaSignalEngine
from src.health_check import run_health_server

logger = logging.getLogger(__name__)

# Son sinyal zamanı referansı (health check için)
_last_signal_time: dict[str, float] = {}


async def scoring_loop(
    buffer: RingBufferManager,
    scoring_engine: ScoringEngine,
    telegram: TelegramNotifier,
    meta_engine: MetaSignalEngine,
) -> None:
    """Her 5 dakikada bir tüm coinleri tara ve sinyal üret."""
    while True:
        await asyncio.sleep(5 * 60)
        try:
            signals = scoring_engine.scan_all()
            if not signals:
                logger.debug("Bu turda sinyal üretilmedi.")
                continue

            logger.info("%d sinyal üretildi.", len(signals))
            min_score: float = config.get("signal_min_score", 6.0)

            for signal in signals:
                if signal.score < min_score:
                    continue

                # Sinyal kartı oluştur
                try:
                    png_bytes = generate_signal_card(signal, buffer)
                except Exception as exc:
                    logger.error("Isı haritası üretme hatası (%s): %s", signal.coin, exc)
                    png_bytes = b""

                # Telegram'a gönder
                try:
                    if png_bytes:
                        await telegram.send_signal(signal, png_bytes)
                    else:
                        # PNG olmadan metin mesajı gönder
                        caption = TelegramNotifier._build_signal_caption(signal)
                        await telegram._send_text(caption, _get_thread_id(signal))
                except Exception as exc:
                    logger.error("Telegram gönderme hatası (%s): %s", signal.coin, exc)

                # SQLite'a kaydet
                try:
                    save_signal(signal)
                except Exception as exc:
                    logger.error("Sinyal kaydetme hatası (%s): %s", signal.coin, exc)

                # Meta sinyal kontrolü
                try:
                    await meta_engine.process_signal(signal)
                except Exception as exc:
                    logger.error("Meta sinyal hatası (%s): %s", signal.coin, exc)

                _last_signal_time["ts"] = time.time()

        except Exception as exc:
            logger.error("Skorlama döngüsü hatası: %s", exc)


def _get_thread_id(signal) -> int:
    """Sinyal skoru ve türüne göre thread ID döndür."""
    strong_score: float = config.get("signal_strong_score", 8.0)
    threads = config.get("telegram_threads", {})
    if signal.signal_type == "S4":
        return threads.get("warning", 3)
    elif signal.score >= strong_score:
        return threads.get("strong", 1)
    return threads.get("normal", 2)


async def connection_monitor(
    coin_supervisor: CoinSupervisor,
    telegram: TelegramNotifier,
) -> None:
    """Bağlantı durumunu izle, kritik durumda Telegram uyarısı gönder."""
    while True:
        await asyncio.sleep(60)
        try:
            connected = coin_supervisor.connected_count()
            total = coin_supervisor.total_managers()
            if total > 0 and connected < 3:
                msg = (
                    f"🚨 Kritik: Sadece {connected}/{total} WebSocket bağlı! "
                    "Sistem kontrolü gerekli."
                )
                logger.error(msg)
                await telegram.send_system(msg)
        except Exception as exc:
            logger.error("Bağlantı izleme hatası: %s", exc)


async def coin_update_loop(coin_supervisor: CoinSupervisor) -> None:
    """Periyodik coin listesi güncelleme."""
    await coin_supervisor.auto_update_loop()


async def main() -> None:
    setup_logging(logging.INFO)

    # Yapılandırma yükle
    config.load_config()
    logger.info("Sistem başlatılıyor... (dry_run=%s)", config.is_dry_run())

    # Veritabanı başlat
    init_db()

    # Bileşenleri oluştur
    buffer = RingBufferManager()
    telegram = TelegramNotifier()
    coin_supervisor = CoinSupervisor(buffer=buffer, telegram_notifier=telegram)
    scoring_engine = ScoringEngine(buffer=buffer)
    meta_engine = MetaSignalEngine(telegram_notifier=telegram)

    # Coin supervisor'ı başlat
    await coin_supervisor.start()

    # Tüm görevleri eş zamanlı başlat
    tasks = [
        asyncio.create_task(
            scoring_loop(buffer, scoring_engine, telegram, meta_engine),
            name="scoring_loop",
        ),
        asyncio.create_task(
            connection_monitor(coin_supervisor, telegram),
            name="connection_monitor",
        ),
        asyncio.create_task(
            coin_update_loop(coin_supervisor),
            name="coin_update_loop",
        ),
        asyncio.create_task(
            run_health_server(coin_supervisor, buffer, _last_signal_time),
            name="health_check",
        ),
    ]

    logger.info("Tüm görevler başlatıldı. Sistem çalışıyor.")
    if config.is_dry_run():
        logger.info("[DRY-RUN] Modu aktif — Telegram'a mesaj gönderilmeyecek.")

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        logger.info("Sistem durduruldu (Ctrl+C).")
    except Exception as exc:
        logger.error("Beklenmeyen hata: %s", exc)
        raise
    finally:
        await coin_supervisor.stop()
        logger.info("Sistem kapatıldı.")


if __name__ == "__main__":
    asyncio.run(main())
