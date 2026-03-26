"""
Phase 1 — Veri Toplayıcı
WebSocket bağlantı yöneticisi: Her borsa/tip için otomatik yeniden bağlanma,
kalp atışı ve durum takibi.
"""

import asyncio
import json
import logging
import time
from enum import Enum
from typing import Callable, Awaitable

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from src import config

logger = logging.getLogger(__name__)


class ConnectionStatus(str, Enum):
    BAGLI = "bağlı"
    YENIDEN_BAGLANIYOR = "yeniden_baglaniyor"
    BAGLI_DEGIL = "bağlı_değil"


class WebSocketManager:
    """
    Tek bir WebSocket akışını yönetir:
    - Otomatik yeniden bağlanma
    - Kalp atışı (heartbeat)
    - Durum takibi
    """

    def __init__(
        self,
        name: str,
        uri: str,
        subscribe_msg: dict | list,
        on_message: Callable[[str, dict], Awaitable[None]],
        telegram_notifier: "TelegramNotifier | None" = None,
    ) -> None:
        self.name = name
        self.uri = uri
        self.subscribe_msg = subscribe_msg
        self.on_message = on_message
        self.telegram_notifier = telegram_notifier

        self.status = ConnectionStatus.BAGLI_DEGIL
        self.last_message_at: float = 0.0
        self._ws = None
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Arka planda bağlantıyı başlat."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name=f"ws_{self.name}")

    async def stop(self) -> None:
        """Bağlantıyı düzgünce kapat."""
        self._running = False
        if self._ws:
            await self._ws.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.status = ConnectionStatus.BAGLI_DEGIL
        logger.info("%s bağlantısı kapatıldı.", self.name)

    async def _run_loop(self) -> None:
        """Yeniden bağlanma döngüsü."""
        max_attempts: int = config.get("reconnect_max_attempts", 5)
        wait_seconds: int = config.get("reconnect_wait_seconds", 60)
        attempt = 0

        while self._running:
            attempt += 1
            try:
                logger.info("%s bağlanıyor... (deneme %d/%d)", self.name, attempt, max_attempts)
                self.status = ConnectionStatus.YENIDEN_BAGLANIYOR

                async with websockets.connect(
                    self.uri,
                    ping_interval=None,  # Manuel heartbeat kullanıyoruz
                    ping_timeout=None,
                    max_size=10 * 1024 * 1024,
                ) as ws:
                    self._ws = ws
                    self.status = ConnectionStatus.BAGLI
                    attempt = 0  # Başarılı bağlantıda sayacı sıfırla
                    logger.info("%s bağlandı.", self.name)

                    # Abonelik mesajını gönder
                    await ws.send(json.dumps(self.subscribe_msg))

                    # Kalp atışı ve mesaj okuma görevleri
                    recv_task = asyncio.create_task(self._recv_loop(ws))
                    hb_task = asyncio.create_task(self._heartbeat_loop(ws))

                    done, pending = await asyncio.wait(
                        [recv_task, hb_task],
                        return_when=asyncio.FIRST_EXCEPTION,
                    )
                    for t in pending:
                        t.cancel()
                    # İstisnaları yükselt
                    for t in done:
                        exc = t.exception()
                        if exc:
                            raise exc

            except asyncio.CancelledError:
                break
            except (ConnectionClosed, WebSocketException, OSError) as exc:
                self.status = ConnectionStatus.YENIDEN_BAGLANIYOR
                msg = (
                    f"⚠️ {self.name} bağlantısı kesildi, yeniden bağlanıyor "
                    f"(deneme {attempt}/{max_attempts}): {exc}"
                )
                logger.warning(msg)
                if self.telegram_notifier:
                    asyncio.create_task(
                        self.telegram_notifier.send_system(msg)
                    )
            except Exception as exc:
                logger.error("%s beklenmeyen hata: %s", self.name, exc)
                self.status = ConnectionStatus.YENIDEN_BAGLANIYOR

            if not self._running:
                break

            if attempt >= max_attempts:
                msg = (
                    f"🚨 {self.name}: {max_attempts} denemede bağlantı kurulamadı. "
                    "Sistem kontrolü gerekli."
                )
                logger.error(msg)
                if self.telegram_notifier:
                    asyncio.create_task(
                        self.telegram_notifier.send_system(msg)
                    )
                await asyncio.sleep(wait_seconds * 2)
                attempt = 0  # Sıfırla, tekrar dene
            else:
                await asyncio.sleep(wait_seconds)

    async def _recv_loop(self, ws) -> None:
        """Gelen mesajları oku ve işle."""
        async for raw in ws:
            self.last_message_at = time.time()
            try:
                data = json.loads(raw)
                await self.on_message(self.name, data)
            except json.JSONDecodeError as exc:
                logger.warning("%s JSON parse hatası: %s", self.name, exc)
            except Exception as exc:
                logger.error("%s mesaj işleme hatası: %s", self.name, exc)

    async def _heartbeat_loop(self, ws) -> None:
        """Belirli aralıklarla ping gönder; cevap gelmezse bağlantıyı kes."""
        interval: int = config.get("heartbeat_interval_seconds", 30)
        while True:
            await asyncio.sleep(interval)
            try:
                pong = await ws.ping()
                await asyncio.wait_for(pong, timeout=10)
            except asyncio.TimeoutError:
                logger.warning("%s kalp atışı zaman aşımı, yeniden bağlanıyor.", self.name)
                raise ConnectionClosed(None, None)
            except Exception as exc:
                raise exc
