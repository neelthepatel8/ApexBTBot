import base64
import requests 
import time
from solana.rpc.types import TxOpts
from solders import message

from solders.transaction import VersionedTransaction  # type: ignore
from solana.rpc.commitment import Processed
from apexbtbot.constants import WSOL_RAW

def _buy(client, token_address, wallet_address, keypair, amount_in_native):
    MAX_API_RETRIES = 3
    MAX_TX_RETRIES = 3
    
    for tx_attempt in range(MAX_TX_RETRIES):
        try:
            # Calculate amount with decimals
            amount_in_native_without_decimals = int(amount_in_native * 1e9)
            
            # Get quote with retry
            quote_response = None
            for api_attempt in range(MAX_API_RETRIES):
                try:
                    quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={WSOL_RAW}&outputMint={token_address}&amount={amount_in_native_without_decimals}"
                    quote_response = requests.get(url=quote_url, timeout=10).json()
                    break
                except Exception as e:
                    if api_attempt == MAX_API_RETRIES - 1:
                        raise Exception(f"Failed to get quote after {MAX_API_RETRIES} attempts: {str(e)}")
                    time.sleep(1)

            # Get swap transaction with retry
            payload = {
                "quoteResponse": quote_response,
                "userPublicKey": wallet_address,
                "wrapUnwrapSOL": True,
                "computeUnitPriceMicroLamports": 1000,  # Add priority fee
                "dynamicComputeUnitLimit": True
            }
            
            for api_attempt in range(MAX_API_RETRIES):
                try:
                    swap_response = requests.post(
                        url="https://quote-api.jup.ag/v6/swap", 
                        json=payload,
                        timeout=10
                    ).json()
                    swap_route = swap_response['swapTransaction']
                    break
                except Exception as e:
                    if api_attempt == MAX_API_RETRIES - 1:
                        raise Exception(f"Failed to get swap route after {MAX_API_RETRIES} attempts: {str(e)}")
                    time.sleep(1)

            # Build and sign transaction
            raw_transaction = VersionedTransaction.from_bytes(base64.b64decode(swap_route))
            signature = keypair.sign_message(message.to_bytes_versioned(raw_transaction.message))
            signed_txn = VersionedTransaction.populate(raw_transaction.message, [signature])

            # Send transaction with corrected options
            opts = TxOpts(
                skip_preflight=False,
                preflight_commitment=Processed
            )
            
            result = client.send_raw_transaction(txn=bytes(signed_txn), opts=opts)
            transaction_id = result['result']
            print(f"Transaction sent: {transaction_id}")

            # Wait for confirmation
            max_retries = 60
            retry_count = 0
            
            while retry_count < max_retries:
                try:
                    confirm_result = client.get_signature_statuses([transaction_id])
                    status = confirm_result['result']['value'][0]
                    
                    if status is not None:
                        if status.get('err') is not None:
                            print(f"Transaction failed with error: {status['err']}")
                            break
                        return transaction_id
                    
                    time.sleep(0.5)
                    retry_count += 1
                    
                except Exception as e:
                    print(f"Error checking status: {str(e)}")
                    time.sleep(0.5)
                    retry_count += 1

            if retry_count >= max_retries:
                print("Transaction timed out waiting for confirmation")
                continue

        except Exception as e:
            print(f"Attempt {tx_attempt + 1} failed: {str(e)}")
            if tx_attempt < MAX_TX_RETRIES - 1:
                time.sleep(2)
                continue
            raise e

    raise Exception(f"Failed to complete transaction after {MAX_TX_RETRIES} attempts")