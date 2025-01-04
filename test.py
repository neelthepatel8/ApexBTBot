from apexbtbot.wallet import Wallet

eth_address = "0x995b7F0bfDb1020eb05CA08d92B8B16c86Bb9D41"

# Fetch ETH balance
eth_balance = Wallet.get_evm_balance(eth_address)
print(f"ETH Balance: {eth_balance} ETH")

# Fetch tracked ERC-20 token balances
erc20_balances = Wallet.get_erc20_balances(eth_address)
print("ERC-20 Token Balances:", erc20_balances)
