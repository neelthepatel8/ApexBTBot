from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from dotenv import load_dotenv
from web3 import Web3

import os
import time

from apexbtbot.database import Database
from apexbtbot.wallet import Wallet
from apexbtbot.abi import router_abi 

db = Database()
db.init()

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ETH_NODE_URL = os.getenv("ETH_NODE_URL")
UNISWAP_ROUTER_ADDRESS = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"

w3 = Web3(Web3.HTTPProvider(ETH_NODE_URL))


uniswap_router = w3.eth.contract(
    address=w3.to_checksum_address(UNISWAP_ROUTER_ADDRESS), abi=router_abi
)


async def create_wallet_for_user(user_id):
    evm_wallet = Wallet.create_evm_wallet()
    solana_wallet = Wallet.create_solana_wallet()

    db.add_wallet(
        user_id=user_id,
        evm_address=evm_wallet["address"],
        evm_private_key=evm_wallet["encrypted_private_key"],
        solana_address=solana_wallet["address"],
        solana_private_key=solana_wallet["encrypted_private_key"],
    )

    return evm_wallet, solana_wallet


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = db.get_user_by_telegram_id(user.id)

    if not user_data:
        db.add_user(user.id, user.full_name)
        user_data = db.get_user_by_telegram_id(user.id)

    wallet = db.get_wallet_by_user_id(user_data["id"])
    if wallet:
        await update.message.reply_text(
            f"Welcome back to ApexBT Bot! Here are your wallet details:\n"
            f"EVM Wallet: {wallet['evm_address']}\nSolana Wallet: {wallet['solana_address']}",
        )
        return

    evm_wallet, solana_wallet = await create_wallet_for_user(user_data["id"])
    await update.message.reply_text(
        f"Welcome to ApexBT Bot! Your wallets have been created:\n"
        f"EVM Wallet: {evm_wallet['address']}\nSolana Wallet: {solana_wallet['address']}",
    )


async def check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = db.get_user_by_telegram_id(user.id)

    if not user_data:
        await update.message.reply_text(
            "You are not registered. Use /start to register."
        )
        return

    wallet = db.get_wallet_by_user_id(user_data["id"])
    if not wallet:
        await update.message.reply_text(
            "You don't have a wallet. Use /start to create one."
        )
        return

    evm_address = wallet.get("evm_address")
    solana_address = wallet.get("solana_address")

    evm_balance = "N/A"
    sol_balance = "N/A"

    if evm_address:
        try:
            evm_balance = Wallet.get_evm_balance(evm_address)
            evm_balance = f"{evm_balance:.4f} ETH"
        except Exception as e:
            print(f"Error fetching EVM balance for {evm_address}: {e}")
            evm_balance = "Error fetching balance"

    if solana_address:
        try:
            sol_balance = Wallet.get_solana_balance(solana_address)
            sol_balance = f"{sol_balance:.4f} SOL"
        except Exception as e:
            print(f"Error fetching Solana balance for {solana_address}: {e}")
            sol_balance = "Error fetching balance"

    try:
        await context.bot.send_message(
            chat_id=user.id,
            text=f"Your Wallet Balances:\n**EVM Wallet**: `{evm_balance}`\n**Solana Wallet**: `{sol_balance}`",
            parse_mode="MarkdownV2",
        )
    except Exception as e:
        print(f"Error sending private message: {e}")
        await update.message.reply_text(
            "Could not send a private message. Please make sure you've started the bot in private."
        )


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args

    if len(args) < 4:
        await update.message.reply_text(
            "Usage: /buy <TOKEN_ADDRESS> <AMOUNT> <SLIPPAGE> <GAS_FEES>\n"
            "Example: /buy 0xTokenAddressHere 0.5 2 50"
        )
        return

    # Parse user inputs
    token_address = args[0]
    try:
        amount_in_eth = float(args[1])
        slippage = float(args[2])
        gas_fees = float(args[3])
    except ValueError:
        await update.message.reply_text(
            "Invalid input. Ensure amount, slippage, and gas fees are numbers."
        )
        return

    # Validate inputs
    if amount_in_eth <= 0 or slippage <= 0 or gas_fees <= 0:
        await update.message.reply_text(
            "Amount, slippage, and gas fees must be positive values."
        )
        return

    # Fetch user's wallet
    user = update.effective_user
    user_data = db.get_user_by_telegram_id(user.id)

    if not user_data:
        await update.message.reply_text(
            "You are not registered. Use /start to register."
        )
        return

    wallet = db.get_wallet_by_user_id(user_data["id"])
    if not wallet:
        await update.message.reply_text(
            "You don't have a wallet. Use /start to create one."
        )
        return

    evm_private_key = Wallet.decrypt_private_key(wallet["evm_private_key"])
    sender_address = wallet["evm_address"]

    try:
        # Path: ETH -> Token
        path = [
            w3.to_checksum_address("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"),  # WETH
            w3.to_checksum_address(token_address),
        ]

        # Amount to send in ETH (in wei)
        amount_in_wei = Web3.to_wei(amount_in_eth, "ether")

        # Fetch token price and calculate minimum output based on slippage
        try:
            print("Fetching token price...")
            amounts_out = uniswap_router.functions.getAmountsOut(amount_in_wei, path).call()
            print(f"Amounts out: {amounts_out}")
            min_tokens_out = int(
                amounts_out[1] * (1 - slippage / 100)
            )  # Adjust for slippage
        except Exception as e:
            print(f"Error fetching token price: {e}")
            await update.message.reply_text(
                "Error fetching token price. Please verify the token address or try again later."
            )
            return

        # Encode the call data for swapExactETHForTokens
        swap_data = uniswap_router.encodeABI(
            fn_name="swapExactETHForTokens",
            args=[
                min_tokens_out,  # Minimum tokens to receive
                path,  # Swap path
                w3.to_checksum_address(sender_address),  # Recipient address
                int(time.time()) + 120,  # Deadline: 2 minutes
            ],
        )

        # Build the transaction
        transaction = {
            "to": uniswap_router.address,
            "from": sender_address,
            "value": amount_in_wei,  # ETH to send
            "data": swap_data,
            "gas": 200000,  # Gas limit
            "gasPrice": Web3.to_wei(gas_fees, "gwei"),
            "nonce": w3.eth.get_transaction_count(sender_address),
        }

        # Sign and send the transaction
        signed_tx = w3.eth.account.sign_transaction(transaction, private_key=evm_private_key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)

        await update.message.reply_text(
            f"Transaction sent successfully! Tx Hash: {tx_hash.hex()}"
        )

    except Exception as e:
        print(f"Error during buy transaction: {e}")
        await update.message.reply_text(
            "An error occurred while processing your transaction. Please try again."
        )


def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("balance", check_balance))
    application.add_handler(CommandHandler("buy", buy))

    print("ApexBT Bot is now running!")
    application.run_polling()


if __name__ == "__main__":
    main()
