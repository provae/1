import requests
import logging
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger("telegram")


def send_telegram_message(text: str):
    """Stuurt een bericht naar de gebruiker via de Telegram bot."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram niet geconfigureerd, bericht niet verstuurd.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            logger.error(f"Telegram fout: {resp.text}")
    except Exception as e:
        logger.error(f"Telegram exception: {e}")


def notify_buy(mint: str, amount_sol: float, tx_sig: str):
    msg = (
        f"🟢 <b>BUY</b>\n"
        f"Mint: <code>{mint}</code>\n"
        f"Bedrag: {amount_sol} SOL\n"
        f"Tx: <code>{tx_sig}</code>"
    )
    send_telegram_message(msg)


def notify_sell(mint: str, pnl_pct: float, reason: str, tx_sig: str):
    emoji = "🟢" if pnl_pct >= 0 else "🔴"
    msg = (
        f"{emoji} <b>SELL</b> ({reason})\n"
        f"Mint: <code>{mint}</code>\n"
        f"PnL: {pnl_pct:+.1f}%\n"
        f"Tx: <code>{tx_sig}</code>"
    )
    send_telegram_message(msg)


def notify_error(text: str):
    send_telegram_message(f"⚠️ <b>ERROR</b>\n{text}")


def notify_status(text: str):
    send_telegram_message(f"ℹ️ {text}")
