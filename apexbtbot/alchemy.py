import requests
import random
import time
import os
from dotenv import load_dotenv

load_dotenv()

ETH_TOKEN_ADDRESS = "0x4200000000000000000000000000000000000006"

class AlchemyAPIWrapper:
    def __init__(self, api_url, max_retries=5, base_delay=1):
        self.api_url = api_url
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.prices_url = os.getenv("PRICES_NODE_URL")

        self.headers = {
            "accept": "application/json",
            "content-type": "application/json",
        }

    def _make_request_with_retry(self, payload, prices=False, endpoint=None):
        
        url = self.api_url
        if prices:
            url = self.prices_url

            if endpoint:
                url += f'/{endpoint}' 

        for attempt in range(self.max_retries):
            try:
                response = requests.post(
                    url, headers=self.headers, json=payload
                )

                if response.status_code == 429:
                    if "Retry-After" in response.headers:
                        delay = int(response.headers["Retry-After"])
                    else:
                        delay = (self.base_delay * (2**attempt)) + (
                            random.uniform(0, 1)
                        )

                    time.sleep(delay)
                    continue

                elif response.status_code != 200:
                    print(
                        f"Request {payload} failed with status {response.status_code}. Retrying... (Attempt {attempt + 1}/{self.max_retries})"
                    )
                    delay = (self.base_delay * (2**attempt)) + (random.uniform(0, 1))
                    time.sleep(delay)
                    continue

                data = response.json()

                if "error" in data:
                    error_message = data["error"].get(
                        "message", "Unknown JSON-RPC error"
                    )
                    print(
                        f"JSON-RPC error: {error_message}. Retrying... (Attempt {attempt + 1}/{self.max_retries})"
                    )
                    delay = (self.base_delay * (2**attempt)) + (random.uniform(0, 1))
                    time.sleep(delay)
                    continue

                return data

            except requests.exceptions.RequestException as e:
                if attempt == self.max_retries - 1: 
                    print(f"All retry attempts failed. Final error: {e}")
                    return None

                delay = (self.base_delay * (2**attempt)) + (random.uniform(0, 1))
                print(
                    f"Request error: {e}. Retrying after {delay:.2f} seconds (Attempt {attempt + 1}/{self.max_retries})"
                )
                time.sleep(delay)

        return None

    def get_token_balances(self, wallet_address, token_type="erc20"):
        payload = {
            "id": 1,
            "jsonrpc": "2.0",
            "method": "alchemy_getTokenBalances",
            "params": [wallet_address, token_type],
        }

        return self._make_request_with_retry(payload)

    def get_token_metadata(self, token_address):
        payload = {
            "id": 1,
            "jsonrpc": "2.0",
            "method": "alchemy_getTokenMetadata",
            "params": [token_address],
        }

        return self._make_request_with_retry(payload)

    def get_token_price_in_usd(self, token_address):
        payload = {
            "addresses": [
                {
                    "network": "base-mainnet",
                    "address": token_address,
                }
            ]
        }

        return self._make_request_with_retry(payload, prices=True, endpoint="tokens/by-address")

    def get_token_balances_and_prices(self, wallet_address, currency="USD"):

        payload = {
            "id": 1,
            "jsonrpc": "2.0",
            "method": "alchemy_getTokenBalancesAndPrices",
            "params": [wallet_address, {"currency": currency}],
        }

        return self._make_request_with_retry(payload)

    def get_eth_price(self):
        try:
            response = self.get_token_price_in_usd(ETH_TOKEN_ADDRESS)
            price_in_usd = float(response.get("data", [])[0].get("prices", [])[0].get("value", 0.0))
            return price_in_usd

        except:
            return 3456.00