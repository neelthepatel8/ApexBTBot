import os
import base64
from cryptography.fernet import Fernet
from web3 import Web3
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.api import Client
from dotenv import load_dotenv

from decimal import Decimal

from apexbtbot.abi import erc20 as erc20abi
from apexbtbot.tokens import erc20 as erc20_tokens
from apexbtbot import web3utils

load_dotenv()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
ETH_NODE_URL = os.getenv("ETH_NODE_URL")
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
    def get_erc20_balances(address, with_address=False):
  
        w3 = Web3(Web3.HTTPProvider(ETH_NODE_URL))
        balances = {}

        token_addresses = {}
        for symbol, token_address in erc20_tokens.items():
            try:
                token_contract = w3.eth.contract(
                    address=w3.to_checksum_address(token_address),
                    abi=erc20abi
                )
                balance = token_contract.functions.balanceOf(address).call()
                decimals = token_contract.functions.decimals().call()
                balances[symbol] = balance / (10 ** decimals)
                token_addresses[symbol] = token_address
            except Exception as e:
                print(f"Error fetching balance for token {symbol}: {e}")
        
        if with_address:
            return balances, token_addresses
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
        
    @staticmethod
    async def build_balance_string(wallet, w3):
        evm_address = wallet.get("evm_address")
        balances = {}
        try:
            eth_price_usd = web3utils.fetch_eth_to_usd()
            eth_balance = Wallet.get_evm_balance(evm_address)
            eth_usd_value = eth_balance * eth_price_usd
            balances["ETH"] = f"{eth_balance:.4f} ETH (${eth_usd_value:.2f})"
        except Exception as e:
            print(f"Error fetching ETH balance for {evm_address}: {e}")
            balances["ETH"] = "Error fetching balance"

        try:
            erc20_balances, token_addresses = Wallet.get_erc20_balances(evm_address, with_address=True)
            for symbol, balance in erc20_balances.items():
                if balance > 0.0:
                    try:
                        token_address = token_addresses[symbol]
                        # Special handling for USDC
                        if token_address.lower() == "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913".lower():
                            # USDC is already in USD terms
                            token_usd_value = balance
                            balances[symbol] = f"{balance:.4f} (${token_usd_value:.3f})"
                        else:
                            # For other tokens, get their ETH price and convert to USD
                            _, _, _, token_price_eth = await web3utils.get_token_info(token_address, w3)
                            token_usd_value = Decimal(balance) * Decimal(token_price_eth) * Decimal(eth_price_usd)
                            balances[symbol] = f"{balance:.4f} (${token_usd_value:.3f})"
                    except Exception as price_error:
                        print(f"Error fetching price for {symbol}: {price_error}")
                        balances[symbol] = f"{balance:.4f}".replace(".", "\\.")
        except Exception as e:
            print(f"Error fetching ERC-20 token balances: {e}")

        total_usd_value = eth_usd_value
        for symbol, balance_str in balances.items():
            if symbol != "ETH" and "($" in balance_str:
                usd_value = float(balance_str.split("($")[1].split(")")[0].replace("$", ""))
                total_usd_value += usd_value

        balance_message = f"Total Portfolio Value: <code>${f'{total_usd_value:.2f}'}</code>\n\n"
        balance_message += "Your Positions:\n"
        for symbol, balance in balances.items():
            balance_message += f"{symbol}: <code>{balance}</code>\n"

        return balance_message