import logging
from solders.keypair import Keypair
import base58
from config import PRIVATE_KEY

logger = logging.getLogger("wallet")


def load_keypair() -> Keypair:
    """Laadt het keypair uit de PRIVATE_KEY env variable (base58 string van Phantom)."""
    try:
        secret_bytes = base58.b58decode(PRIVATE_KEY)
        keypair = Keypair.from_bytes(secret_bytes)
        logger.info(f"Wallet geladen: {keypair.pubkey()}")
        return keypair
    except Exception as e:
        raise RuntimeError(f"Kon private key niet laden: {e}")
