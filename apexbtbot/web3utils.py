from web3 import Web3
from apexbtbot import abi
import requests

UNISWAP_ROUTER_ADDRESS = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D" 

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
    token_address = Web3.to_checksum_address(token_address)
    token_contract = web3.eth.contract(address=token_address, abi=abi.erc20)
    name = token_contract.functions.name().call()
    symbol = token_contract.functions.symbol().call()
    decimals = token_contract.functions.decimals().call()
    weth_address = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
    uniswap_router = web3.eth.contract(address=Web3.to_checksum_address(UNISWAP_ROUTER_ADDRESS), abi=abi.uniswap_router)
    
    amount_in = Web3.to_wei(1, "ether")
    try:
        amounts_out = uniswap_router.functions.getAmountsOut(amount_in, [weth_address, token_address]).call()
        tokens_per_eth = Web3.from_wei(amounts_out[1], "ether")
        price_in_eth = 1 / tokens_per_eth
    except Exception as e:
        print(f"Error fetching price for token {token_address}: {e}")
        price_in_eth = None
        
    return name, symbol, decimals, price_in_eth

async def get_token_price(token_address: str, w3: Web3) -> float:
    try:
        pair_address = await get_pair_address(token_address, w3)
        pair_contract = w3.eth.contract(
            address=w3.to_checksum_address(pair_address),
            abi=abi.uniswap_v2_pair
        )
        
        reserves = pair_contract.functions.getReserves().call()
        token0 = pair_contract.functions.token0().call()
        
        if token_address.lower() == token0.lower():
            return reserves[1] / reserves[0]
        else:
            return reserves[0] / reserves[1] 
            
    except Exception as e:
        print(f"Error getting token price: {e}")
        raise


async def get_pair_address(token_address: str, w3) -> str:
    try:
        factory_address = "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f"
        weth_address = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
        
        factory_contract = w3.eth.contract(
            address=w3.to_checksum_address(factory_address),
            abi=abi.uniswap_v2_factory
        )
        
        pair_address = factory_contract.functions.getPair(
            w3.to_checksum_address(token_address),
            w3.to_checksum_address(weth_address)
        ).call()
        
        if pair_address == "0x0000000000000000000000000000000000000000":
            raise Exception("No liquidity pair found")
            
        return pair_address
        
    except Exception as e:
        print(f"Error getting pair address: {e}")
        raise