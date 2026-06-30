import logging
import requests
import time
from config import HELIUS_RPC_URL

logger = logging.getLogger("filters")


def mint_authority_revoked(mint: str) ->bool:
    """
    Controleert via getAccountInfo of de mint authority is ingetrokken.
    Probeert meerdere keren omdat nieuwe Pump.fun mints soms nog niet
    direct beschikbaar zijn op de RPC.
    """

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": [
            mint,
            {
                "encoding": "jsonParsed",
                "commitment": "confirmed",
            },
        ],
    }

    for attempt in range(5):
        try:
            resp = requests.post(
                HELIUS_RPC_URL,
                json=payload,
                timeout=10,
            )

            data = resp.json()
            info = data.get("result", {}).get("value")

            if info:
                parsed = (
                    info.get("data", {})
                    .get("parsed", {})
                    .get("info", {})
                )

                mint_authority = parsed.get("mintAuthority")

                return mint_authority is None

            logger.warning(
                f"Geen account info voor mint {mint} (poging {attempt+1}/5)"
            )

            time.sleep(0.5)

        except Exception as e:
            logger.error(f"Fout bij mint authority check: {e}")
            time.sleep(0.5)

    return False
