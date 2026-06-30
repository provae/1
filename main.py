import asyncio
import json
import logging
import time
import websockets
import requests

from config import (
    HELIUS_WS_URL,
    HELIUS_RPC_URL,
    PUMP_FUN_PROGRAM_ID,
    BUY_AMOUNT_SOL,
    TAKE_PROFIT_PCT,
    STOP_LOSS_PCT,
    validate_config,
)
from filters import mint_authority_revoked
from pumpfun import (
    buy_token,
    sell_token,
    get_bonding_curve_pda,
    get_token_balance_raw,
    get_position_value_sol,
)
from telegram_notifier import notify_buy, notify_sell, notify_error, notify_status

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("main")

open_positions = {}

POLL_INTERVAL_SECONDS = 5


async def listen_for_new_mints():
    """Luistert via Helius WebSocket naar nieuwe pump.fun token creaties."""
    subscribe_msg = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "logsSubscribe",
        "params": [
            {"mentions": [PUMP_FUN_PROGRAM_ID]},
            {"commitment": "processed"},
        ],
    }

    while True:
        try:
            async with websockets.connect(HELIUS_WS_URL) as ws:
                await ws.send(json.dumps(subscribe_msg))
                logger.info("WebSocket verbonden, luisteren naar nieuwe mints...")
                notify_status("Bot online, luistert naar nieuwe pump.fun coins.")

                async for message in ws:
                    try:
                        data = json.loads(message)
                        await handle_log_message(data)
                    except Exception as e:
                        logger.error(f"Fout bij verwerken log message: {e}")

        except Exception as e:
            logger.error(f"WebSocket verbinding verbroken: {e}. Herverbinden in 5s...")
            notify_error(f"WebSocket verbroken: {e}")
            await asyncio.sleep(5)


async def handle_log_message(data: dict):
    """Detecteert een nieuwe mint-creatie in de log en triggert de buy-flow."""
    try:
        result = data.get("params", {}).get("result", {})
        logs = result.get("value", {}).get("logs", [])
        signature = result.get("value", {}).get("signature")

        is_create = any("Instruction: Create" in log for log in logs)
        if not is_create or not signature:
            return

        mint = await extract_mint_from_tx(signature)
        if not mint:
            return

        logger.info(f"Nieuwe mint gedetecteerd: {mint}")
        await process_new_mint(mint)

    except Exception as e:
        logger.error(f"Fout in handle_log_message: {e}")


async def extract_mint_from_tx(signature: str):
    """Haalt het mint-adres op uit de transactie via direct RPC call met retries."""
    for attempt in range(3):
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTransaction",
                "params": [
                    signature,
                    {
                        "encoding": "jsonParsed",
                        "maxSupportedTransactionVersion": 0,
                        "commitment": "confirmed"
                    }
                ]
            }

            resp = requests.post(HELIUS_RPC_URL, json=payload, timeout=10)
            data = resp.json()

            if "error" in data:
                logger.warning(f"RPC error bij getTransaction voor {signature}: {data['error']}")
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return None

            result = data.get("result")
            if not result:
                logger.warning(f"Geen result voor {signature} (poging {attempt+1}/3)")
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return None

            meta = result.get("meta")
            if not meta:
                logger.warning(f"Geen meta voor {signature}")
                return None

            post_balances = meta.get("postTokenBalances", [])
            if not post_balances:
                logger.info(
                    f"Geen post_token_balances voor {signature} (waarschijnlijk geen nieuwe mint-tx)"
                )
                return None

            for bal in post_balances:
                return bal.get("mint")

            return None

        except Exception as e:
            logger.error(f"Kon mint niet extraheren uit tx {signature} (poging {attempt+1}/3): {e}")
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)
                continue
            return None


async def process_new_mint(mint: str):
    """Filtert en koopt een nieuwe mint als hij door de check komt."""
    if mint in open_positions:
        return

    passed = mint_authority_revoked(mint)
    if not passed:
        logger.info(f"Mint {mint} geweigerd: mint authority niet ingetrokken.")
        return

    try:
        sig = buy_token(mint, BUY_AMOUNT_SOL)
        await asyncio.sleep(10)  # Verhoogd naar 10 seconden voor transactie bevestiging
        token_amount = get_token_balance_raw(mint)

        open_positions[mint] = {
            "entry_sol": BUY_AMOUNT_SOL,
            "buy_time": time.time(),
            "buy_tx": sig,
            "token_amount": token_amount,
        }

        notify_buy(mint, BUY_AMOUNT_SOL, sig)

        logger.info(
            f"Gekocht: {mint} voor {BUY_AMOUNT_SOL} SOL, tokens: {token_amount}, tx: {sig}"
        )

    except AttributeError as e:
        logger.warning(f"AttributeError bij buy flow voor {mint}: {e}")
        notify_error(f"Buy flow error voor {mint}: Kon token balance niet ophalen (transactie mogelijk nog niet bevestigd)")
    except Exception as e:
        logger.error(f"Buy mislukt voor {mint}: {e}")
        notify_error(f"Buy mislukt voor {mint}: {e}")


def get_current_value_sol(mint: str, token_amount: int) -> float:
    """Haalt de huidige waarde in SOL op van token_amount tokens via de bonding curve."""
    return get_position_value_sol(mint, token_amount)


async def monitor_positions():
    """Checkt periodiek alle open posities op take-profit / stop-loss."""
    while True:
        for mint in list(open_positions.keys()):
            position = open_positions[mint]

            try:
                token_amount = position.get("token_amount", 0)

                if token_amount <= 0:
                    continue

                current_value = get_current_value_sol(mint, token_amount)
                entry = position["entry_sol"]
                pnl_pct = ((current_value - entry) / entry) * 100

                if pnl_pct >= TAKE_PROFIT_PCT or pnl_pct <= -STOP_LOSS_PCT:
                    reason = "TP" if pnl_pct >= TAKE_PROFIT_PCT else "SL"

                    sig = sell_token(mint, token_amount)

                    notify_sell(mint, pnl_pct, reason, sig)

                    del open_positions[mint]

                    logger.info(
                        f"Verkocht {mint} ({reason}), PnL: {pnl_pct:.1f}%"
                    )

            except Exception as e:
                logger.error(f"Fout bij monitoren positie {mint}: {e}")

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def main():
    validate_config()

    await asyncio.gather(
        listen_for_new_mints(),
        monitor_positions(),
    )


if __name__ == "__main__":
    asyncio.run(main())
