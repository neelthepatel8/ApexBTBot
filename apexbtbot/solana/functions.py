import base64
import asyncio 
import os
import httpx
import subprocess 
from dataclasses import dataclass

from solana.rpc.types import TxOpts
from solders import message
from solders.transaction import VersionedTransaction  # type: ignore
from solana.rpc.commitment import Confirmed
from apexbtbot.constants import WSOL_RAW
from solders.keypair import Keypair # type: ignore
from pprint import pprint 
from dotenv import load_dotenv

from apexbtbot.solana.util import parse_base58_tx

load_dotenv()

SOL_NODE_URL = os.getenv("SOL_NODE_URL")

@dataclass
class BuyTokenParams:
    private_key: str
    token_mint: str         
    sol_amount: float  
    slippage: int = 200
    rpc: str = SOL_NODE_URL

@dataclass
class SellTokenParams:
    private_key: str
    token_mint: str         
    token_amount: float  
    token_decimals: int   
    slippage: int = 200
    rpc: str = SOL_NODE_URL

async def __buy(client, token_address, keypair: Keypair, amount_in_native):
    quote_response = await __quote(input_mint=WSOL_RAW, output_mint=token_address, amount=amount_in_native)
    swap_response = await __swap(quote_response, keypair)
    swap_route = swap_response['swapTransaction']

    print(f"Swap route recieved from Jupiter API: {swap_route}")

    raw_transaction = VersionedTransaction.from_bytes(base64.b64decode(swap_route))

    pprint(raw_transaction)
    signature = keypair.sign_message(message.to_bytes_versioned(raw_transaction.message))

    print(f"Signature: {signature}")
    signed_txn = VersionedTransaction.populate(raw_transaction.message, [signature])

    opts = TxOpts(
        skip_preflight=True,
        preflight_commitment=Confirmed,
    )
    
    result = client.send_raw_transaction(txn=bytes(signed_txn), opts=opts)
    transaction_id = result['result']

    confirm_result = client.get_signature_statuses([transaction_id])
    status = confirm_result['result']['value'][0]
            
    if status is not None:
        if status.get('err') is not None:
            print(f"Transaction failed with error: {status['err']}")
    
    print(f"Transaction confirmed! https://solscan.io/tx/{transaction_id}")
    return transaction_id
    
async def __quote(input_mint: str, output_mint: str, amount: float, decimals: int = 9):
    url = f"https://quote-api.jup.ag/v6/quote"
    params = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": int(amount * 10**decimals),
    }
    
    response = await httpx.AsyncClient().get(url, params=params)
    return response.json()

async def __swap(quote_response, keypair):
    url = f"https://quote-api.jup.ag/v6/swap"

    payload = {
        "quoteResponse": quote_response,
        "userPublicKey": keypair.pubkey().__str__(),
        "wrapUnwrapSOL": True,
        "dynamicComputeUnitLimit": True,
        "prioritizationFeeLamports": 'auto',
    }
    swap_response = await httpx.AsyncClient().post(url, json=payload)

    return swap_response.json()

async def _execute_swap(
    input_mint: str,
    output_mint: str,
    amount: int,
    private_key: str,
    slippage: int,
    rpc: str
):
    
    print(input_mint)
    print(output_mint)
    print(amount)
    print(private_key)
    print(slippage)
    try:
        process = await asyncio.create_subprocess_exec(
            'node', 'js/swap.js',
            '--private-key', private_key,
            '--input-mint', input_mint,
            '--output-mint', output_mint,
            '--amount', str(amount),
            '--slippage', str(slippage),
            '--rpc', rpc,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            print(f"Error: {stderr.decode()}")
            return None
            
        output = stdout.decode()
        print(output)
        
        for line in output.split('\n'):
            if line.startswith('Txid:'):
                txid = line.split('Txid: ')[1].strip()
                print("Recieved txid: ", txid)

                return parse_base58_tx(txid)
        
        return None
        
    except Exception as e:
        print(f"Failed to execute swap: {e}")
        return None

async def _buy(params: BuyTokenParams):
    amount = int(params.sol_amount * 1e9)
    print(f"Buying with {params.sol_amount} = {amount}")
    txid =  await _execute_swap(
        input_mint=WSOL_RAW,
        output_mint=params.token_mint,
        amount=amount,
        private_key=params.private_key,
        slippage=params.slippage,
        rpc=params.rpc
    )
    print(f"Recieved txid 2: {txid}")
    return txid

async def _sell(params: SellTokenParams):
    amount = int(params.token_amount * (10 ** params.token_decimals))
    print(f"Selling: {amount}")
    return await _execute_swap(
        input_mint=params.token_mint,
        output_mint=WSOL_RAW,
        amount=amount,
        private_key=params.private_key,
        slippage=params.slippage,
        rpc=params.rpc
    )

