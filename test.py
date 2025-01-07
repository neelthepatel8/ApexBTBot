from apexbtbot.database import Database
from apexbtbot.wallet import Wallet
from cryptography.fernet import Fernet
from web3 import Web3
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.api import Client
from dotenv import load_dotenv
from spl.token.client import Token
from spl.token.constants import TOKEN_PROGRAM_ID
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TokenAccountOpts

db = Database()
db.init()

user = db.get_user_by_telegram_id(5627329018)
wallet = db.get_wallet_by_user_id(user["id"])

solana_wallet_address = wallet["solana_address"]

balance_string = Wallet.build_solana_balance_string(solana_wallet_address)