"""
Phase 4 — SQLite Sinyal Logu
Tüm üretilen sinyalleri veritabanına kaydeder.
"""

import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from src import config
from src.scoring_engine import Signal

logger = logging.getLogger(__name__)


def _get_db_path() -> str:
    return config.get("db_path", "signals.db")


def init_db() -> None:
    """Veritabanını başlat ve tabloyu oluştur (yoksa)."""
    db_path = _get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                coin            TEXT,
                seviye          REAL,
                skor            REAL,
                sinyal_turu     TEXT,
                spot_toplam     REAL,
                vadeli_toplam   REAL,
                borsa_onay      INTEGER,
                agirlikli_skor  REAL,
                funding_rate    REAL,
                hacim_degisimi  REAL,
                timestamp       TEXT,
                sonuc           TEXT DEFAULT 'bekliyor'
            )
        """)
        conn.commit()
    logger.info("Veritabanı başlatıldı: %s", db_path)


def save_signal(signal: Signal) -> int:
    """Sinyali veritabanına kaydet. Yeni satır ID'sini döndür."""
    db_path = _get_db_path()
    ts = datetime.fromtimestamp(signal.timestamp, tz=timezone.utc).isoformat()

    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO signals
                (coin, seviye, skor, sinyal_turu, spot_toplam, vadeli_toplam,
                 borsa_onay, agirlikli_skor, funding_rate, hacim_degisimi, timestamp, sonuc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal.coin,
                signal.level,
                signal.score,
                signal.signal_type,
                signal.spot_total,
                signal.futures_total,
                signal.exchange_count,
                signal.weighted_exchange_score,
                signal.funding_rate,
                signal.volume_change_pct,
                ts,
                "bekliyor",
            ),
        )
        conn.commit()
        row_id = cur.lastrowid

    logger.debug("Sinyal kaydedildi (id=%d): %s %.4f skor=%.2f", row_id, signal.coin, signal.level, signal.score)
    return row_id


def update_result(signal_id: int, result: str) -> None:
    """Sinyal sonucunu güncelle (tuttu / tutmadi / bekliyor)."""
    db_path = _get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE signals SET sonuc = ? WHERE id = ?",
            (result, signal_id),
        )
        conn.commit()
    logger.debug("Sinyal sonucu güncellendi (id=%d): %s", signal_id, result)


def fetch_recent_signals(days: int = 7) -> list[dict]:
    """Son N günün sinyallerini çek."""
    db_path = _get_db_path()
    cutoff = datetime.fromtimestamp(
        time.time() - days * 86400, tz=timezone.utc
    ).isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM signals WHERE timestamp >= ? ORDER BY timestamp DESC",
            (cutoff,),
        ).fetchall()

    return [dict(row) for row in rows]
