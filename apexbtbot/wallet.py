import os
import base64
from cryptography.fernet import Fernet
from web3 import Web3
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.api import Client
from dotenv import load_dotenv

from apexbtbot.abi import erc20 as erc20abi
from apexbtbot.tokens import erc20 as erc20_tokens

load_dotenv()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
ETH_NODE_URL = os.getenv("ETH_NODE_URL", "https://mainnet.infura.io/v3/YOUR_INFURA_PROJECT_ID")
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")

cipher = Fernet(ENCRYPTION_KEY)

class Wallet:
    @staticmethod
    def create_evm_wallet():
        w3 = Web3(Web3.HTTPProvider(ETH_NODE_URL))
        account = w3.eth.account.create()
        private_key = account.key.hex()
        encrypted_private_key = cipher.encrypt(private_key.encode()).decode()
        return {
            "address": account.address,
            "encrypted_private_key": encrypted_private_key
        }

    @staticmethod
    def get_evm_balance(address):
        w3 = Web3(Web3.HTTPProvider(ETH_NODE_URL))
        try:
            balance_wei = w3.eth.get_balance(address)  
            balance_eth = w3.from_wei(balance_wei, 'ether')  
            return float(balance_eth)
        except Exception as e:
            print(f"Error fetching EVM wallet balance: {e}")
            return 0.0
        
    @staticmethod
    def get_erc20_balances(address):
  
        w3 = Web3(Web3.HTTPProvider(ETH_NODE_URL))
        balances = {}

        for symbol, token_address in erc20_tokens.items():
            try:
                token_contract = w3.eth.contract(
                    address=w3.to_checksum_address(token_address),
                    abi=erc20abi
                )
                balance = token_contract.functions.balanceOf(address).call()
                decimals = token_contract.functions.decimals().call()
                balances[symbol] = balance / (10 ** decimals)
            except Exception as e:
                print(f"Error fetching balance for token {symbol}: {e}")
        return balances

    @staticmethod
    def create_solana_wallet():
        keypair = Keypair()
        private_key = base64.b64encode(bytes(keypair)).decode() 
        encrypted_private_key = cipher.encrypt(private_key.encode()).decode()
        return {
            "address": str(keypair.pubkey()),
            "encrypted_private_key": encrypted_private_key
        }

    @staticmethod
    def get_solana_balance(public_key):
        client = Client(SOLANA_RPC_URL)
        pubkey = Pubkey.from_string(public_key)
        response = client.get_balance(pubkey)

        if response.value:
            return response.value / 1e9 
        else:
            return 0

    @staticmethod
    def decrypt_private_key(encrypted_key):
        return cipher.decrypt(encrypted_key.encode()).decode()

    @staticmethod
    def validate_evm_address(address):
        return Web3.isAddress(address)

    @staticmethod
    def validate_solana_address(address):
        try:
            Pubkey.from_string(address)
            return True
        except ValueError:
            return False