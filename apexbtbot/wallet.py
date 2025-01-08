import os
import base64
import base58 

import requests

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

from apexbtbot.alchemy import AlchemyAPIWrapper

load_dotenv()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
ETH_NODE_URL = os.getenv("ETH_NODE_URL")
PRICES_NODE_URL = os.getenv("PRICES_NODE_URL")
SOLANA_RPC_URL = os.getenv("SOL_NODE_URL")

cipher = Fernet(ENCRYPTION_KEY)

alchemy = AlchemyAPIWrapper(ETH_NODE_URL)

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
    def create_solana_wallet():
        keypair = Keypair()
        private_key = base58.b58encode(bytes(keypair.secret_key)).decode()
        encrypted_private_key = cipher.encrypt(private_key.encode()).decode()
        return {
            "address": str(keypair.public_key),
            "encrypted_private_key": encrypted_private_key
        }

    @staticmethod
    def get_solana_balance(public_key):
        client = Client(SOLANA_RPC_URL)
        pubkey = Pubkey.from_string(public_key)
        response = client.get_balance(pubkey)

        if response['result']:
            return response['result']['value'] / 1e9 
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
    def is_spam_token(metadata):
        if not metadata:
            return True
            
        name = metadata.get('name', '').lower()
        symbol = metadata.get('symbol', '').lower()
        
        spam_indicators = [
            'claim', 'airdrop', 'visit', 'free', 'click',
            '.com', '.xyz', '.net', '.org', 'reward',
            'getgbg', 'http', 'https', 'www.', 'telegram',
            't.me/', 'twitter'
        ]
        
        for indicator in spam_indicators:
            if indicator in name or indicator in symbol:
                return True
                
        if len(name) > 30 or len(symbol) > 10:
            return True
            
        return False

    @staticmethod
    def process_token_metadata(alchemy, token, token_info_dict):
        try:
            contract_address = token["contractAddress"]
            raw_balance = int(token["tokenBalance"], 16)
            if raw_balance <= 0:
                return None
                
            metadata_response = alchemy.get_token_metadata(contract_address)
            if not metadata_response or 'result' not in metadata_response:
                return None
                
            metadata = metadata_response['result']
            if Wallet.is_spam_token(metadata):
                return None
                
            decimals = metadata.get('decimals', 18)
            balance = raw_balance / (10 ** decimals)
            
            token_info = {
                'balance': balance,
                'symbol': metadata.get('symbol', ''),
                'name': metadata.get('name', ''),
                'decimals': decimals,
                'price_in_usd': 0,
                'value_in_usd': 0
            }
            
            return {
                'address': contract_address,
                'info': token_info,
                'network_info': {
                    "network": "base-mainnet",
                    "address": contract_address
                }
            }
            
        except Exception as e:
            print(f"Error processing token metadata: {e}")
            return None

    @staticmethod
    def fetch_token_prices(alchemy, tokens_to_price, token_info_dict):
        try:
            if not tokens_to_price:
                return token_info_dict
                
            prices_payload = {"addresses": tokens_to_price}
            prices_response = alchemy._make_request_with_retry(prices_payload, prices=True, endpoint="tokens/by-address")
            
            if prices_response and 'data' in prices_response:
                for token_data in prices_response['data']:
                    address = token_data.get('address')
                    if address in token_info_dict:
                        try:
                            price = float(token_data.get('prices', [])[0].get('value', 0.0))
                            token_info_dict[address]['price_in_usd'] = price
                            token_info_dict[address]['value_in_usd'] = price * token_info_dict[address]['balance']
                        except (IndexError, ValueError) as e:
                            print(f"Error processing price for {address}: {e}")
                            
            return token_info_dict
            
        except Exception as e:
            print(f"Error fetching batch prices: {e}")
            return token_info_dict

    @staticmethod
    def get_evm_token_balances(wallet_address, with_address=False):
        alchemy = AlchemyAPIWrapper(ETH_NODE_URL)
        
        response = alchemy.get_token_balances(wallet_address)
        if not response:
            return {}
            
        token_balances = response.get("result", {}).get("tokenBalances", [])
        token_info_dict = {}
        tokens_to_price = []
        
        for token in token_balances:
            token_data = Wallet.process_token_metadata(alchemy, token, token_info_dict)
            if token_data:
                token_info_dict[token_data['address']] = token_data['info']
                tokens_to_price.append(token_data['network_info'])
        
        token_info_dict = Wallet.fetch_token_prices(alchemy, tokens_to_price, token_info_dict)
        
        if with_address:
            return token_info_dict, list(token_info_dict.keys())
        return token_info_dict
    
    @staticmethod
    def build_evm_balance_string(wallet_address, no_title=False, no_eth=False):
        
        token_balances = Wallet.get_evm_token_balances(wallet_address)
        eth_balance = Wallet.get_evm_balance(wallet_address)
        eth_value_in_usd = alchemy.get_eth_price() * eth_balance

        balance_compiled_message = f"ETH: <code>{eth_balance:.4f} (${eth_value_in_usd:.2f})</code>\n"
        total_usd_value = eth_value_in_usd

        for _, data in token_balances.items():
            balance = data["balance"]
            symbol = data["symbol"]
            value_in_usd = data["value_in_usd"]

            total_usd_value += value_in_usd

            if no_eth and symbol == "ETH":
                continue
            
            if balance > 0.0:
                balance_compiled_message += f"{symbol}: <code>{balance:.4f} (${value_in_usd:.2f})</code>\n"
                    
        balance_message = ""

        if not no_title:
            balance_message = f"<b>EVM Wallet Positions:</b>\n\n"
            balance_message += f"Total Portfolio Value: <code>${total_usd_value:.2f}</code>\n\n"
            balance_message += "<b>Your Positions:</b>\n"

        balance_message += balance_compiled_message
        return balance_message
    
    @staticmethod
    def get_solana_token_balances(public_key):
        client = Client(SOLANA_RPC_URL, commitment=Confirmed)
        pubkey = Pubkey.from_string(public_key)
        try:
            response = client.get_token_accounts_by_owner(
                pubkey,
                TokenAccountOpts(program_id=TOKEN_PROGRAM_ID, encoding="base64")
            )

            token_balances = {}

            for account in response['result']['value']:
                account_data = account['account']['data']
                raw_data = base64.b64decode(account_data[0])
                mint = str(base58.b58encode(raw_data[:32]), 'utf-8')
                amount = int.from_bytes(raw_data[64:72], 'little')
                token_balances[mint] = amount 

            
            mint_data_url = f"https://api-v3.raydium.io/mint/ids?mints={','.join(token_balances.keys())}"
            price_data_url = f"https://api-v3.raydium.io/mint/price?mints={','.join(token_balances.keys())}"
            
            mint_data_response = requests.get(mint_data_url, timeout=5).json()
            price_data_response = requests.get(price_data_url, timeout=5).json()

        
            if mint_data_response['success'] == True:
                mint_data = mint_data_response['data']
            
            if price_data_response['success'] == True:
                price_data = price_data_response['data']

            built_token_balances = {}
            for data in mint_data:
                address = data['address']
                symbol = data['symbol']
                name = data['name']
                decimals = data['decimals']
                price = float(price_data[address])
                balance = token_balances[address] / (10 ** decimals)

                if balance <= 0:
                    continue
                    
                built_token_balances[address] = {
                    'balance': balance,
                    'symbol': symbol,
                    'name': name,
                    'price_in_usd': price,
                    'value_in_usd': price * balance
                }
                    
            return built_token_balances
            
            
        except Exception as e:
            print(f"Error fetching Solana token balances: {e}")
            return {}

    @staticmethod
    def build_solana_balance_string(public_key, no_title=False):
        token_balances = Wallet.get_solana_token_balances(public_key)
        sol_balance = Wallet.get_solana_balance(public_key)

        print(token_balances)
        print(sol_balance)
        try:
            sol_price_response = requests.get(
                "https://api.jup.ag/price/v2?ids=So11111111111111111111111111111111111111112",
                timeout=5
            ).json()
            sol_price = float(sol_price_response['data']['So11111111111111111111111111111111111111112']['price'])
        except (requests.exceptions.RequestException, KeyError, ValueError):
            print("Failed to fetch SOL price")
            sol_price = 0
            
        sol_value_in_usd = sol_price * sol_balance
        
        balance_compiled_message = f"SOL: <code>{sol_balance:.4f} (${sol_value_in_usd:.2f})</code>\n"
        total_usd_value = sol_value_in_usd
        
        for _, data in token_balances.items():
            balance = data["balance"]
            symbol = data["symbol"]
            value_in_usd = data["value_in_usd"]
            
            total_usd_value += value_in_usd
            
            if balance > 0.0:
                balance_compiled_message += f"{symbol}: <code>{balance:.4f} (${value_in_usd:.2f})</code>\n"
                
        balance_message = ""
        
        if not no_title:
            balance_message = f"<b>Solana Wallet Positions:</b>\n\n"
            balance_message += f"Total Portfolio Value: <code>${total_usd_value:.2f}</code>\n\n"
            balance_message += "<b>Your Positions:</b>\n"
            
        balance_message += balance_compiled_message

        print(balance_message)
        return balance_message    
    
    @staticmethod
    def get_keypair_from_private_key(private_key):
        return Keypair.from_bytes(private_key)
