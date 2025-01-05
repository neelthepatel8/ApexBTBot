from web3 import Web3
from apexbtbot import abi
import requests

UNISWAP_SWAP_ROUTER_ADDRESS = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD" 
UNISWAP_QUOTER_ROUTER_ADDRESS = "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a" 
UNISWAP_FACTORY_ROUTER_ADDRESS = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"

WETH = "0x4200000000000000000000000000000000000006"

def fetch_eth_to_usd():
    url = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        eth_to_usd = data["ethereum"]["usd"]
        return eth_to_usd
    except requests.exceptions.RequestException as e:
        print(f"Error fetching ETH/USD price: {e}")
        return None

async def get_token_info(token_address, web3):
    try:
        WETH = "0x4200000000000000000000000000000000000006"
        
        token_address = Web3.to_checksum_address(token_address)
        token_contract = web3.eth.contract(address=token_address, abi=abi.erc20)
        name = token_contract.functions.name().call()
        symbol = token_contract.functions.symbol().call()
        decimals = token_contract.functions.decimals().call()
        
        # Use the correct ABI for factory
        factory = web3.eth.contract(
            address=UNISWAP_FACTORY_ROUTER_ADDRESS, 
            abi=abi.uniswap_factory
        )
        
        # Try to find the pool
        fee_tiers = [500, 3000, 10000]
        pool_address = None
        active_fee = None
        
        for fee in fee_tiers:
            try:
                pool = factory.functions.getPool(WETH, token_address, fee).call()
                if pool != "0x0000000000000000000000000000000000000000":
                    pool_address = pool
                    active_fee = fee
                    break
            except Exception as e:
                print(f"Error checking pool for fee {fee}: {e}")
                continue
        
        if not pool_address:
            raise Exception("No active pool found")
            
        quoter = web3.eth.contract(address=UNISWAP_QUOTER_ROUTER_ADDRESS, abi=abi.uniswap_quote)
        
        amount_in = Web3.to_wei(1, "ether")
        params = (WETH, token_address, amount_in, active_fee, 0)
        
        result = quoter.functions.quoteExactInputSingle(params).call()
        amount_out = result[0]
        
        if decimals == 6:
            price_in_token = amount_out / 10**6
        else:
            price_in_token = Web3.from_wei(amount_out, "ether")
            
        return name, symbol, decimals, price_in_token
        
    except Exception as e:
        print(f"Error fetching price for token {token_address}: {e}")
        return None, None, None, None


async def get_token_price(token_address: str, w3: Web3) -> float:
    try:
        pool_address, fee_tier = await get_pair_address(token_address, w3)
        
        quoter = w3.eth.contract(
            address=w3.to_checksum_address("0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"),
            abi=abi.uniswap_quote
        )

        weth_address = "0x4200000000000000000000000000000000000006"
        
        token_contract = w3.eth.contract(
            address=w3.to_checksum_address(token_address),
            abi=abi.erc20
        )
        decimals = token_contract.functions.decimals().call()
        
        amount_in = 10 ** decimals 
        params = (
            token_address,
            weth_address,
            amount_in,
            fee_tier,
            0  
        )
        
        result = quoter.functions.quoteExactInputSingle(params).call()
        amount_out = result[0] 
        price_in_eth = w3.from_wei(amount_out, "ether")
        
        return float(price_in_eth)
    except Exception as e:
        print(f"Error getting token price: {e}")
        raise


async def get_pair_address(token_address: str, w3) -> str:
    try:
        weth_address = "0x4200000000000000000000000000000000000006"
        factory_contract = w3.eth.contract(
            address=w3.to_checksum_address("0x33128a8fC17869897dcE68Ed026d694621f6FDfD"),  # Base Uniswap V3 Factory
            abi=[{
                "inputs": [
                    {"internalType": "address", "name": "tokenA", "type": "address"},
                    {"internalType": "address", "name": "tokenB", "type": "address"},
                    {"internalType": "uint24", "name": "fee", "type": "uint24"}
                ],
                "name": "getPool",
                "outputs": [{"internalType": "address", "name": "", "type": "address"}],
                "stateMutability": "view",
                "type": "function"
            }]
        )
        
        fee_tiers = [500, 3000, 10000]
        
        for fee in fee_tiers:
            pool_address = factory_contract.functions.getPool(
                w3.to_checksum_address(token_address),
                w3.to_checksum_address(weth_address),
                fee
            ).call()
            
            if pool_address != "0x0000000000000000000000000000000000000000":
                return pool_address, fee
        
        raise Exception("No liquidity pool found across any fee tier")
    except Exception as e:
        print(f"Error getting pool address: {e}")
        raise
    
def get_token_address(symbol):

    base_url = "https://api.coingecko.com/api/v3/coins/list"
    try:
        response = requests.get(base_url, timeout=10)
        response.raise_for_status()
        tokens = response.json()

        for token in tokens:
            if token["symbol"].lower() == symbol.lower():
                token_details_url = f"https://api.coingecko.com/api/v3/coins/{token['id']}"
                token_details_response = requests.get(token_details_url, timeout=10)
                token_details_response.raise_for_status()
                token_details = token_details_response.json()

                return token_details.get("platforms", {}).get("ethereum")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching token address for symbol {symbol}: {e}")
        return None