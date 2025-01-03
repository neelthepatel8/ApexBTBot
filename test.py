from apexbtbot.wallet import Wallet

eth_address = "0xa9Ee12d7aE7129E79AB742B494dcE3f7beE130F8"
eth_balance = Wallet.get_evm_balance(eth_address)
print(f"Ethereum Wallet Balance: {eth_balance} ETH")
