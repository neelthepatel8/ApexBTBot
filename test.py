import requests
import base58
import base64
import json
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solders import message
from solana.rpc.api import Client
from solana.rpc.types import TxOpts
from solana.rpc.commitment import Processed, Confirmed
from apexbtbot.wallet import Wallet
import time

from apexbtbot.database import Database
db = Database()
db.init()
user_data = db.get_user_by_telegram_id("7103256395")
wallet = db.get_wallet_by_user_id(user_data["id"])
decoded = base64.b64decode(Wallet.decrypt_private_key(wallet["solana_private_key"]))
keypair = Wallet.get_keypair_from_private_key(decoded)


