import asyncio
import base64
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solders import message
from solana.rpc.api import Client
from solana.rpc.types import TxOpts
from solana.rpc.commitment import Processed, Confirmed
from apexbtbot.wallet import Wallet
from apexbtbot.database import Database
from apexbtbot.solana.functions import _buy, _sell, BuyTokenParams, SellTokenParams

db = Database()
db.init()
user_data = db.get_user_by_telegram_id("7103256395")
wallet = db.get_wallet_by_user_id(user_data["id"])
private_key = Wallet.decrypt_private_key(wallet["solana_private_key"])
decoded = base64.b64decode(private_key)
keypair = Wallet.get_keypair_from_private_key(decoded)
client = Client("https://mainnet.helius-rpc.com/?api-key=d8965fa9-a70f-4b56-a16f-ee72dc18bd4f")

token_address = "74SBV4zDXxTRgv1pEMoECskKBkZHc2yGPnc7GYVepump"

async def main():
    buy_params = BuyTokenParams(
        private_key=private_key,
        token_mint=token_address,  
        sol_amount=0.02
    )
    txid = await _buy(buy_params)

    print(f"Tx Successful! check on: https://www.solscan.io/tx/{txid}")

    
    sell_params = SellTokenParams(
        private_key=private_key,
        token_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", 
        token_amount=3,
        token_decimals=6
    )

    txid = await _sell(sell_params)
    print(f"Tx Successful! check on: https://www.solscan.io/tx/{txid}")


if __name__ == "__main__":
    asyncio.run(main())
