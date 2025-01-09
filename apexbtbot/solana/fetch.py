from typing import Optional
import struct

from solders.pubkey import Pubkey  # type: ignore
from solders.instruction import AccountMeta, Instruction  # type: ignore
from solana.rpc.commitment import Processed
from solana.rpc.types import MemcmpOpts

from apexbtbot.solana.keys import AmmV4PoolKeys
from apexbtbot.solana.layouts import LIQUIDITY_STATE_LAYOUT_V4, MARKET_STATE_LAYOUT_V3
from apexbtbot.constants import RAYDIUM_AMM_V4, DEFAULT_QUOTE_MINT, WSOL

def fetch_amm_v4_pool_keys(client, pair_address: str) -> Optional[AmmV4PoolKeys]:

    def bytes_of(value):
        if not (0 <= value < 2**64):
            raise ValueError("Value must be in the range of a u64 (0 to 2^64 - 1).")
        return struct.pack("<Q", value)

    try:
        amm_id = Pubkey.from_string(pair_address)
        amm_data = client.get_account_info_json_parsed(
            amm_id, commitment=Processed
        ).value.data

        amm_data_decoded = LIQUIDITY_STATE_LAYOUT_V4.parse(amm_data)

        marketId = Pubkey.from_bytes(amm_data_decoded.serumMarket)

        marketInfo = client.get_account_info_json_parsed(
            marketId, commitment=Processed
        ).value.data

        market_decoded = MARKET_STATE_LAYOUT_V3.parse(marketInfo)
        vault_signer_nonce = market_decoded.vault_signer_nonce

        ray_authority_v4 = Pubkey.from_string(
            "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1"
        )
        open_book_program = Pubkey.from_string(
            "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX"
        )
        token_program_id = Pubkey.from_string(
            "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
        )

        pool_keys = AmmV4PoolKeys(
            amm_id=amm_id,
            base_mint=Pubkey.from_bytes(market_decoded.base_mint),
            quote_mint=Pubkey.from_bytes(market_decoded.quote_mint),
            base_decimals=amm_data_decoded.coinDecimals,
            quote_decimals=amm_data_decoded.pcDecimals,
            open_orders=Pubkey.from_bytes(amm_data_decoded.ammOpenOrders),
            target_orders=Pubkey.from_bytes(amm_data_decoded.ammTargetOrders),
            base_vault=Pubkey.from_bytes(amm_data_decoded.poolCoinTokenAccount),
            quote_vault=Pubkey.from_bytes(amm_data_decoded.poolPcTokenAccount),
            market_id=marketId,
            market_authority=Pubkey.create_program_address(
                seeds=[bytes(marketId), bytes_of(vault_signer_nonce)],
                program_id=open_book_program,
            ),
            market_base_vault=Pubkey.from_bytes(market_decoded.base_vault),
            market_quote_vault=Pubkey.from_bytes(market_decoded.quote_vault),
            bids=Pubkey.from_bytes(market_decoded.bids),
            asks=Pubkey.from_bytes(market_decoded.asks),
            event_queue=Pubkey.from_bytes(market_decoded.event_queue),
            ray_authority_v4=ray_authority_v4,
            open_book_program=open_book_program,
            token_program_id=token_program_id,
        )

        return pool_keys
    except Exception as e:
        print(f"Error fetching pool keys: {e}")
        return None


def make_amm_v4_swap_instruction(
    amount_in: int,
    minimum_amount_out: int,
    token_account_in: Pubkey,
    token_account_out: Pubkey,
    accounts: AmmV4PoolKeys,
    owner: Pubkey,
) -> Instruction:
    try:

        keys = [
            AccountMeta(
                pubkey=accounts.token_program_id, is_signer=False, is_writable=False
            ),
            AccountMeta(pubkey=accounts.amm_id, is_signer=False, is_writable=True),
            AccountMeta(
                pubkey=accounts.ray_authority_v4, is_signer=False, is_writable=False
            ),
            AccountMeta(pubkey=accounts.open_orders, is_signer=False, is_writable=True),
            AccountMeta(
                pubkey=accounts.target_orders, is_signer=False, is_writable=True
            ),
            AccountMeta(pubkey=accounts.base_vault, is_signer=False, is_writable=True),
            AccountMeta(pubkey=accounts.quote_vault, is_signer=False, is_writable=True),
            AccountMeta(
                pubkey=accounts.open_book_program, is_signer=False, is_writable=False
            ),
            AccountMeta(pubkey=accounts.market_id, is_signer=False, is_writable=True),
            AccountMeta(pubkey=accounts.bids, is_signer=False, is_writable=True),
            AccountMeta(pubkey=accounts.asks, is_signer=False, is_writable=True),
            AccountMeta(pubkey=accounts.event_queue, is_signer=False, is_writable=True),
            AccountMeta(
                pubkey=accounts.market_base_vault, is_signer=False, is_writable=True
            ),
            AccountMeta(
                pubkey=accounts.market_quote_vault, is_signer=False, is_writable=True
            ),
            AccountMeta(
                pubkey=accounts.market_authority, is_signer=False, is_writable=False
            ),
            AccountMeta(pubkey=token_account_in, is_signer=False, is_writable=True),
            AccountMeta(pubkey=token_account_out, is_signer=False, is_writable=True),
            AccountMeta(pubkey=owner, is_signer=True, is_writable=False),
        ]

        data = bytearray()
        discriminator = 9
        data.extend(struct.pack("<B", discriminator))
        data.extend(struct.pack("<Q", amount_in))
        data.extend(struct.pack("<Q", minimum_amount_out))
        swap_instruction = Instruction(RAYDIUM_AMM_V4, bytes(data), keys)

        return swap_instruction
    except Exception as e:
        print(f"Error occurred: {e}")
        return None


def get_amm_v4_reserves(client, pool_keys: AmmV4PoolKeys) -> tuple:
    try:
        quote_vault = pool_keys.quote_vault
        quote_decimal = pool_keys.quote_decimals
        quote_mint = pool_keys.quote_mint

        base_vault = pool_keys.base_vault
        base_decimal = pool_keys.base_decimals
        base_mint = pool_keys.base_mint

        balances_response = client.get_multiple_accounts_json_parsed(
            [quote_vault, base_vault], Processed
        )
        balances = balances_response.value

        quote_account = balances[0]
        base_account = balances[1]

        quote_account_balance = quote_account.data.parsed["info"]["tokenAmount"][
            "uiAmount"
        ]
        base_account_balance = base_account.data.parsed["info"]["tokenAmount"][
            "uiAmount"
        ]

        if quote_account_balance is None or base_account_balance is None:
            print("Error: One of the account balances is None.")
            return None, None, None

        if base_mint == WSOL:
            base_reserve = quote_account_balance
            quote_reserve = base_account_balance
            token_decimal = quote_decimal
        else:
            base_reserve = base_account_balance
            quote_reserve = quote_account_balance
            token_decimal = base_decimal

        return base_reserve, quote_reserve, token_decimal

    except Exception as e:
        print(f"Error occurred: {e}")
        return None, None, None


def fetch_pair_address_from_rpc(
    client,
    program_id: Pubkey,
    token_mint: str,
    quote_offset: int,
    base_offset: int,
    data_length: int,
) -> list:

    def fetch_pair(base_mint: str, quote_mint: str) -> list:
        memcmp_filter_base = MemcmpOpts(offset=quote_offset, bytes=quote_mint)
        memcmp_filter_quote = MemcmpOpts(offset=base_offset, bytes=base_mint)
        try:
            print(
                f"Fetching pair addresses for base_mint: {base_mint}, quote_mint: {quote_mint}"
            )
            response = client.get_program_accounts(
                program_id,
                commitment=Processed,
                filters=[data_length, memcmp_filter_base, memcmp_filter_quote],
            )
            accounts = response.value
            if accounts:
                print(f"Found {len(accounts)} matching AMM account(s).")
                return [account.pubkey.__str__() for account in accounts]
            else:
                print("No matching AMM accounts found.")
        except Exception as e:
            print(f"Error fetching AMM pair addresses: {e}")
        return []

    pair_addresses = fetch_pair(token_mint, DEFAULT_QUOTE_MINT)

    if not pair_addresses:
        print("Retrying with reversed base and quote mints...")
        pair_addresses = fetch_pair(DEFAULT_QUOTE_MINT, token_mint)

    return pair_addresses

def get_amm_v4_pair_from_rpc(client, token_mint: str) -> list:
    return fetch_pair_address_from_rpc(
        client,
        program_id=RAYDIUM_AMM_V4,
        token_mint=token_mint,
        quote_offset=400,
        base_offset=432,
        data_length=752,
    )

from typing import List, Dict, Optional
import aiohttp
import asyncio

class JupiterAggregator:
    BASE_URL = "https://quote-api.jup.ag/v6"
    
    async def get_token_pools(self, input_mint: str) -> List[Dict]:
        try:
            wsol_mint = "So11111111111111111111111111111111111111112"
            
            # Try different amounts to see all possible routes
            amounts = [100000, 1000000, 10000000]  # 0.1 SOL, 1 SOL, 10 SOL
            all_routes = []
            
            async with aiohttp.ClientSession() as session:
                for amount in amounts:
                    url = f"{self.BASE_URL}/quote"
                    params = {
                        "inputMint": input_mint,
                        "outputMint": wsol_mint,
                        "amount": str(amount),
                        "slippageBps": 50,
                        "onlyDirectRoutes": "true"  # Try to force direct routes
                    }
                    
                    async with session.get(url, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            if 'routePlan' in data:
                                for route in data['routePlan']:
                                    swap_info = route['swapInfo']
                                    # Only collect direct routes between input and WSOL
                                    if (swap_info['inputMint'] == input_mint and 
                                        swap_info['outputMint'] == wsol_mint):
                                        all_routes.append({
                                            'pool_id': swap_info['ammKey'],
                                            'label': swap_info['label'],
                                            'fee_amount': swap_info['feeAmount'],
                                            'direct_route': True
                                        })
            
            # Remove duplicates while preserving order
            seen = set()
            unique_routes = []
            for route in all_routes:
                if route['pool_id'] not in seen:
                    seen.add(route['pool_id'])
                    unique_routes.append(route)
                    
            return unique_routes
                    
        except Exception as e:
            print(f"Error accessing Jupiter API: {e}")
            return []
