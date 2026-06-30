import os

# Deze waardes komen NOOIT hier in de code te staan.
# Je zet ze als Environment Variables in Railway (tabblad "Variables").

HELIUS_API_KEY = os.environ.get("HELIUS_API_KEY")
PRIVATE_KEY = os.environ.get("PRIVATE_KEY")  # base58 string uit Phantom
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Trading parameters
BUY_AMOUNT_SOL = float(os.environ.get("BUY_AMOUNT_SOL", "0.02"))  # hoeveel SOL per trade
TAKE_PROFIT_PCT = float(os.environ.get("TAKE_PROFIT_PCT", "50"))   # +50%
STOP_LOSS_PCT = float(os.environ.get("STOP_LOSS_PCT", "30"))       # -30%
SLIPPAGE_BPS = int(os.environ.get("SLIPPAGE_BPS", "500"))          # 5%

HELIUS_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
HELIUS_WS_URL = f"wss://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

PUMP_FUN_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

def validate_config():
    missing = []
    if not HELIUS_API_KEY:
        missing.append("HELIUS_API_KEY")
    if not PRIVATE_KEY:
        missing.append("PRIVATE_KEY")
    if not TELEGRAM_TOKEN:
        missing.append("TELEGRAM_TOKEN")
    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")
    if missing:
        raise RuntimeError(f"Ontbrekende environment variables: {', '.join(missing)}")
