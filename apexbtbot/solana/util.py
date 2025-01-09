import time
import json
from enum import Enum
import requests 
from urllib.parse import quote

from solana.rpc.types import TokenAccountOpts
from solana.rpc.commitment import Processed, Confirmed
from solders.pubkey import Pubkey  # type: ignore
from solders.signature import Signature  # type: ignore

from apexbtbot.constants import WSOL_RAW


def get_token_balance(client, mint_str: str, payer_keypair) -> float | None:

    mint = Pubkey.from_string(mint_str)
    response = client.get_token_accounts_by_owner_json_parsed(
        payer_keypair.pubkey(), TokenAccountOpts(mint=mint), commitment=Processed
    )

    if response.value:
        accounts = response.value
        if accounts:
            token_amount = accounts[0].account.data.parsed["info"]["tokenAmount"][
                "uiAmount"
            ]
            if token_amount:
                return float(token_amount)
    return None


def confirm_txn(
    client, txn_sig: Signature, max_retries: int = 20, retry_interval: int = 3
) -> bool:
    retries = 1

    while retries < max_retries:
        try:
            txn_res = client.get_transaction(
                txn_sig,
                encoding="json",
                commitment=Confirmed,
                max_supported_transaction_version=0,
            )

            txn_json = json.loads(txn_res.value.transaction.meta.to_json())

            if txn_json["err"] is None:
                print("Transaction confirmed... try count:", retries)
                return True

            print("Error: Transaction not confirmed. Retrying...")
            if txn_json["err"]:
                print("Transaction failed.")
                return False
        except Exception as e:
            print("Awaiting confirmation... try count:", retries)
            retries += 1
            time.sleep(retry_interval)

    print("Max retries reached. Transaction confirmation failed.")
    return None


def sol_for_tokens(sol_amount, base_vault_balance, quote_vault_balance, swap_fee=0.25):
    effective_sol_used = sol_amount - (sol_amount * (swap_fee / 100))
    constant_product = base_vault_balance * quote_vault_balance
    updated_base_vault_balance = constant_product / (
        quote_vault_balance + effective_sol_used
    )
    tokens_received = base_vault_balance - updated_base_vault_balance
    return round(tokens_received, 9)


def tokens_for_sol(
    token_amount, base_vault_balance, quote_vault_balance, swap_fee=0.25
):
    effective_tokens_sold = token_amount * (1 - (swap_fee / 100))
    constant_product = base_vault_balance * quote_vault_balance
    updated_quote_vault_balance = constant_product / (
        base_vault_balance + effective_tokens_sold
    )
    sol_received = quote_vault_balance - updated_quote_vault_balance
    return round(sol_received, 9)


def get_token_price(token_address):
    url = f"https://api-v3.raydium.io/mint/price?mints={token_address}"

    response = requests.get(url).json()
    if response['success'] == False:
        print(f"Error getting token price from radiyum")
        return None, None
    
    price_in_usd = float(response['data'][token_address])
    sol_price = get_sol_price()
    price_in_sol = price_in_usd / sol_price

    return price_in_sol, price_in_usd
    
def get_sol_price():
    url = f"https://api-v3.raydium.io/mint/price?mints={WSOL_RAW}"

    response = requests.get(url).json()
    if response['success'] == False:
        print(f"Error getting SOL price from radiyum")
        return None
    
    price_in_usd = float(response['data'][WSOL_RAW])
    return price_in_usd

def get_token_info(token_address):
    
    url = f"https://api-v3.raydium.io/mint/ids?mints={token_address}"

    response = requests.get(url).json()
    if response['success'] == False:
        print(f"Error getting token information from radiyum")
        return None, None, None, None, None, None
    
    data = response['data'][0]
    info = data['name'], data['symbol'], data['decimals']

    prices = get_token_price(token_address)

    return *info, *prices

class DIRECTION(Enum):
    BUY = 0
    SELL = 1

def parse_base58_tx(txid):
    return quote(txid) 
