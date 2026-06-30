import base64
import logging
import struct
import requests
from solders.pubkey import Pubkey
from solders.instruction import Instruction, AccountMeta
from solders.transaction import VersionedTransaction
from solders.message import MessageV0

from config import HELIUS_RPC_URL, PUMP_FUN_PROGRAM_ID, SLIPPAGE_BPS
from wallet import load_keypair

logger = logging.getLogger("pumpfun")

keypair = load_keypair()

PUMP_PROGRAM = Pubkey.from_string(PUMP_FUN_PROGRAM_ID)
SYSTEM_PROGRAM = Pubkey.from_string("11111111111111111111111111111111")
TOKEN_PROGRAM = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOCIATED_TOKEN_PROGRAM = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
RENT_SYSVAR = Pubkey.from_string("SysvarRent111111111111111111111111111111111")

GLOBAL_ACCOUNT = Pubkey.from_string("4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SCkCAjPbqU8RGT")
FEE_RECIPIENT = Pubkey.from_string("CebN5WGQ4jvEPvsVU4EoHEpgzq1VV7AbicfhtW4xC9iM")
EVENT_AUTHORITY = Pubkey.from_string("Ce6TQqeHC9p8KetsN6JsjHK7UTZk7nasjjnr7XxXp9F1")


def _rpc_call(method: str, params: list):
    payload={"jsonrpc":"2.0","id":1,"method":method,"params":params}
    resp=requests.post(HELIUS_RPC_URL,json=payload,timeout=20)
    resp.raise_for_status()
    data=resp.json()
    if "error" in data:
        raise RuntimeError(f"RPC error bij {method}: {data['error']}")
    return data["result"]

def get_bonding_curve_pda(mint: Pubkey) -> Pubkey:
    pda, _ = Pubkey.find_program_address(
        [b"bonding-curve", bytes(mint)], PUMP_PROGRAM
    )
    return pda


def get_associated_token_address(owner: Pubkey, mint: Pubkey) -> Pubkey:
    pda, _ = Pubkey.find_program_address(
        [bytes(owner), bytes(TOKEN_PROGRAM), bytes(mint)],
        ASSOCIATED_TOKEN_PROGRAM,
    )
    return pda


def _get_recent_blockhash():
    result=_rpc_call("getLatestBlockhash",[{"commitment":"confirmed"}])
    from solders.hash import Hash
    return Hash.from_string(result["value"]["blockhash"])

def _build_and_send(instructions: list) -> str:
    recent_blockhash=_get_recent_blockhash()
    msg=MessageV0.try_compile(payer=keypair.pubkey(),instructions=instructions,address_lookup_table_accounts=[],recent_blockhash=recent_blockhash)
    tx=VersionedTransaction(msg,[keypair])
    raw_tx_b64=base64.b64encode(bytes(tx)).decode("utf-8")
    logger.info(f"Using blockhash: {recent_blockhash}")
    logger.info(f"Sending transaction ({len(bytes(tx))} bytes)")
    return _rpc_call("sendTransaction",[raw_tx_b64,{"encoding":"base64","skipPreflight":True,"preflightCommitment":"confirmed","maxRetries":3}])



def buy_token(mint_str: str, amount_sol: float) -> str:
    """
    Koopt een token op de pump.fun bonding curve voor amount_sol SOL.
    """
    mint = Pubkey.from_string(mint_str)
    bonding_curve = get_bonding_curve_pda(mint)
    associated_user = get_associated_token_address(keypair.pubkey(), mint)
    associated_bonding_curve = get_associated_token_address(bonding_curve, mint)

    lamports = int(amount_sol * 1_000_000_000)
    max_sol_cost = int(lamports * (1 + SLIPPAGE_BPS / 10_000))

    discriminator = struct.pack("<Q", 16927863322537952870)
    data = discriminator + struct.pack("<QQ", lamports, max_sol_cost)

    keys = [
        AccountMeta(GLOBAL_ACCOUNT, False, False),
        AccountMeta(FEE_RECIPIENT, False, True),
        AccountMeta(mint, False, False),
        AccountMeta(bonding_curve, False, True),
        AccountMeta(associated_bonding_curve, False, True),
        AccountMeta(associated_user, False, True),
        AccountMeta(keypair.pubkey(), True, True),
        AccountMeta(SYSTEM_PROGRAM, False, False),
        AccountMeta(TOKEN_PROGRAM, False, False),
        AccountMeta(RENT_SYSVAR, False, False),
        AccountMeta(EVENT_AUTHORITY, False, False),
        AccountMeta(PUMP_PROGRAM, False, False),
    ]

    ix = Instruction(PUMP_PROGRAM, data, keys)
    sig = _build_and_send([ix])
    logger.info(f"Buy tx verstuurd: {sig}")

    # Check transactie status
    import time
    time.sleep(2)  # Wacht 2 seconden voor transactie bevestiging
    for attempt in range(3):
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignatureStatuses",
                "params": [[sig], {"searchTransactionHistory": True}]
            }
            resp = requests.post(HELIUS_RPC_URL, json=payload, timeout=10)
            data = resp.json()
            if "error" not in data:
                result = data.get("result", {}).get("value", [])
                if result and result[0]:
                    status = result[0].get("confirmationStatus")
                    err = result[0].get("err")
                    if err:
                        logger.error(f"Buy transactie gefaald: {err}")
                        raise RuntimeError(f"Buy transactie gefaald: {err}")
                    if status == "confirmed" or status == "finalized":
                        logger.info(f"Buy transactie bevestigd: {status}")
                        break
        except Exception as e:
            logger.warning(f"Kon transactie status niet checken (poging {attempt+1}/3): {e}")
            time.sleep(2)

    return sig


def get_bonding_curve_state(mint_str: str):
    """
    Leest de bonding curve account data uit en geeft de virtuele SOL- en
    token-reserves terug via direct RPC call.
    """
    try:
        mint = Pubkey.from_string(mint_str)
        bonding_curve = get_bonding_curve_pda(mint)

        # Direct RPC call instead of client method
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getAccountInfo",
            "params": [
                str(bonding_curve),
                {"encoding": "base64"}
            ]
        }

        resp = requests.post(HELIUS_RPC_URL, json=payload, timeout=10)
        data = resp.json()

        if "error" in data:
            raise RuntimeError(f"RPC error bij getAccountInfo voor {mint_str}: {data['error']}")

        result = data.get("result", {}).get("value")
        if not result:
            raise RuntimeError(f"Geen bonding curve account gevonden voor {mint_str}")

        raw = result.get("data", [])
        if isinstance(raw, list):
            raw = base64.b64decode(raw[0])
        else:
            raw = base64.b64decode(raw)

        offset = 8
        virtual_token_reserves, virtual_sol_reserves = struct.unpack_from(
            "<QQ", raw, offset
        )
        return {
            "virtual_token_reserves": virtual_token_reserves,
            "virtual_sol_reserves": virtual_sol_reserves,
        }
    except Exception as e:
        logger.error(f"Fout bij ophalen bonding curve state voor {mint_str}: {e}")
        raise


def get_token_balance_raw(mint_str: str) -> int:
    """Haalt de raw token balance (met decimals) op van ons wallet voor deze mint via direct RPC call met retries."""
    for attempt in range(5):  # 5 pogingen met wachttijd
        try:
            mint = Pubkey.from_string(mint_str)
            ata = get_associated_token_address(keypair.pubkey(), mint)

            # Direct RPC call instead of client method
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [
                    str(keypair.pubkey()),
                    {"mint": str(mint)},
                    {"encoding": "jsonParsed"}
                ]
            }

            resp = requests.post(HELIUS_RPC_URL, json=payload, timeout=10)
            data = resp.json()

            if "error" in data:
                logger.warning(f"RPC error bij getTokenAccountsByOwner voor {mint_str} (poging {attempt+1}/5): {data['error']}")
                if attempt < 4:
                    import time
                    time.sleep(2 ** attempt)  # Exponential backoff: 2s, 4s, 8s, 16s
                    continue
                return 0

            result = data.get("result", {}).get("value", [])
            if not result:
                logger.warning(f"Geen token account gevonden voor {mint_str} (poging {attempt+1}/5)")
                if attempt < 4:
                    import time
                    time.sleep(2 ** attempt)
                    continue
                return 0

            # Get the first token account balance
            token_account = result[0]
            balance = token_account.get("account", {}).get("data", {}).get("parsed", {}).get("info", {}).get("tokenAmount", {}).get("amount", "0")

            return int(balance)

        except Exception as e:
            logger.error(f"Fout bij ophalen token balance voor {mint_str} (poging {attempt+1}/5): {e}")
            if attempt < 4:
                import time
                time.sleep(2 ** attempt)
                continue
            return 0

    return 0


def get_position_value_sol(mint_str: str, token_amount_raw: int) -> float:
    """
    Berekent de huidige waarde in SOL van token_amount_raw tokens,
    op basis van de actuele bonding curve prijs.
    """
    state = get_bonding_curve_state(mint_str)
    if state["virtual_token_reserves"] == 0:
        return 0.0

    price_per_raw_token = state["virtual_sol_reserves"] / state["virtual_token_reserves"]
    value_lamports = token_amount_raw * price_per_raw_token
    return value_lamports / 1_000_000_000


def sell_token(mint_str: str, token_amount: int) -> str:
    """
    Verkoopt token_amount (raw, met decimals) van mint terug naar SOL.
    """
    mint = Pubkey.from_string(mint_str)
    bonding_curve = get_bonding_curve_pda(mint)
    associated_user = get_associated_token_address(keypair.pubkey(), mint)
    associated_bonding_curve = get_associated_token_address(bonding_curve, mint)

    min_sol_output = 0

    discriminator = struct.pack("<Q", 12502976635542562355)
    data = discriminator + struct.pack("<QQ", token_amount, min_sol_output)

    keys = [
        AccountMeta(GLOBAL_ACCOUNT, False, False),
        AccountMeta(FEE_RECIPIENT, False, True),
        AccountMeta(mint, False, False),
        AccountMeta(bonding_curve, False, True),
        AccountMeta(associated_bonding_curve, False, True),
        AccountMeta(associated_user, False, True),
        AccountMeta(keypair.pubkey(), True, True),
        AccountMeta(SYSTEM_PROGRAM, False, False),
        AccountMeta(TOKEN_PROGRAM, False, False),
        AccountMeta(EVENT_AUTHORITY, False, False),
        AccountMeta(PUMP_PROGRAM, False, False),
    ]

    ix = Instruction(PUMP_PROGRAM, data, keys)
    sig = _build_and_send([ix])
    logger.info(f"Sell tx verstuurd: {sig}")
    return sig
