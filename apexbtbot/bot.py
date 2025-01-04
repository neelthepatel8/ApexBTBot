from telegram import (
    Update, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton
)
from telegram.ext import (
    Application, 
    CommandHandler, 
    ContextTypes, 
    CallbackQueryHandler, 
    ChatMemberHandler, 
    ConversationHandler, 
    MessageHandler, 
    filters
)
from dotenv import load_dotenv
from web3 import Web3

import os
import time

from apexbtbot.database import Database
from apexbtbot.wallet import Wallet
from apexbtbot.abi import router_abi
from apexbtbot.abi import erc20 as erc20abi

db = Database()
db.init()

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ETH_NODE_URL = os.getenv("ETH_NODE_URL")
UNISWAP_ROUTER_ADDRESS = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D" # mainnet
# UNISWAP_ROUTER_ADDRESS = "0xfff9976782d46cc05630d1f6ebab18b2324d6b14"  # testnet

BUY_TOKEN_ADDRESS, BUY_AMOUNT, BUY_CONFIRM = range(3)
SELL_TOKEN_ADDRESS, SELL_AMOUNT, SELL_CONFIRM = range(3)

w3 = Web3(Web3.HTTPProvider(ETH_NODE_URL))

uniswap_router = w3.eth.contract(
    address=w3.to_checksum_address(UNISWAP_ROUTER_ADDRESS), abi=router_abi
)

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_member = update.chat_member
    user = chat_member.new_chat_member.user

    if chat_member.new_chat_member.status == "member" and not user.is_bot:
        await start(update, context)

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


from telegram import InlineKeyboardMarkup, InlineKeyboardButton

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = db.get_user_by_telegram_id(user.id)

    if not user_data:
        db.add_user(user.id, user.full_name)
        user_data = db.get_user_by_telegram_id(user.id)

    wallet = db.get_wallet_by_user_id(user_data["id"])

    if wallet:
        # Inline buttons for actions
        keyboard = [
            [InlineKeyboardButton("💼 Check Balance", callback_data="balance")],
            [InlineKeyboardButton("🛒 Buy Tokens", callback_data="buy")],
            [InlineKeyboardButton("💱 Sell Tokens", callback_data="sell")],
            [InlineKeyboardButton("❓ Help", callback_data="help")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"👋 Welcome back to ApexBT Bot, {user.full_name}!\n\n"
            f"💼 Your Wallet Details:\n"
            f"🔑 EVM Wallet: {wallet['evm_address']}\n"
            f"🔑 Solana Wallet: {wallet['solana_address']} WIP\n\n"
            f"Select an option below to get started:",
            reply_markup=reply_markup,
        )
        return

    evm_wallet, solana_wallet = await create_wallet_for_user(user_data["id"])

    keyboard = [
        [InlineKeyboardButton("💼 Check Balance", callback_data="balance")],
        [InlineKeyboardButton("🛒 Buy Tokens", callback_data="buy")],
        [InlineKeyboardButton("💱 Sell Tokens", callback_data="sell")],
        [InlineKeyboardButton("❓ Help", callback_data="help")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"👋 Welcome to ApexBT Bot, {user.full_name}!\n\n"
        f"💼 Your Wallets Have Been Created:\n"
        f"🔑 EVM Wallet: {evm_wallet['address']}\n"
        f"🔑 Solana Wallet: {solana_wallet['address']} WIP\n\n"
        f"Select an option below to get started:",
        reply_markup=reply_markup,
    )

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "balance":
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Sending your wallet balances to you..."
        )
        await check_balance(update, context)
    elif query.data == "buy":
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Use /buy <TOKEN_ADDRESS> <AMOUNT> <SLIPPAGE> <GAS_FEES> to purchase tokens."
        )
    elif query.data == "sell":
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Use /sell <TOKEN_TO_SELL> <AMOUNT> <SLIPPAGE> <GAS_FEES> <DESTINATION_TOKEN> to sell tokens."
        )
    elif query.data == "help":
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=(
                "Here’s how to use the bot:\n\n"
                "💼 Check Balance: Use /balance.\n"
                "🛒 Buy Tokens: Use /buy <TOKEN_ADDRESS> <AMOUNT> <SLIPPAGE> <GAS_FEES>.\n"
                "💱 Sell Tokens: Use /sell <TOKEN_TO_SELL> <AMOUNT> <SLIPPAGE> <GAS_FEES> <DESTINATION_TOKEN>.\n"
            ),
            parse_mode="Markdown"
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

    balances = {}

    try:
        eth_balance = Wallet.get_evm_balance(evm_address)
        balances["ETH"] = f"{eth_balance:.4f} ETH"
    except Exception as e:
        print(f"Error fetching ETH balance for {evm_address}: {e}")
        balances["ETH"] = "Error fetching balance"

    try:
        erc20_balances = Wallet.get_erc20_balances(evm_address)
        for symbol, balance in erc20_balances.items():
            if balance > 0.0:
                balances[symbol] = f"{balance:.4f} {symbol}"
    except Exception as e:
        print(f"Error fetching ERC-20 token balances: {e}")

    balance_message = "Your Wallet Balances:\n"
    for symbol, balance in balances.items():
        balance_message += f"{symbol}: `{balance}`\n"

    try:
        await context.bot.send_message(
            chat_id=user.id,
            text=balance_message,
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

    if amount_in_eth <= 0 or slippage <= 0 or gas_fees <= 0:
        await update.message.reply_text(
            "Amount, slippage, and gas fees must be positive values."
        )
        return

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

        amount_in_wei = Web3.to_wei(amount_in_eth, "ether")

        amounts_out = uniswap_router.functions.getAmountsOut(amount_in_wei, path).call()
        min_tokens_out = int(amounts_out[1] * (1 - slippage / 100)) 

        transaction = uniswap_router.functions.swapExactETHForTokens(
            min_tokens_out, 
            path,  
            w3.to_checksum_address(sender_address),  
            int(time.time()) + 600,
        ).build_transaction({
            "from": sender_address,
            "value": amount_in_wei, 
            "gas": 200000,  
            "gasPrice": Web3.to_wei(gas_fees, "gwei"),
            "nonce": w3.eth.get_transaction_count(sender_address),
        })

        signed_tx = w3.eth.account.sign_transaction(transaction, private_key=evm_private_key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)

        await update.message.reply_text(
            f"Transaction sent successfully! Tx Hash: {tx_hash.hex()}"
        )

    except Exception as e:
        print(f"Error during buy transaction: {e}")
        await update.message.reply_text(
            "An error occurred while processing your transaction. Please try again."
        )

async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args

    if len(args) < 5:
        await update.message.reply_text(
            "Usage: /sell <TOKEN_TO_SELL_ADDRESS> <AMOUNT> <SLIPPAGE> <GAS_FEES> <DESTINATION_TOKEN_ADDRESS>\n"
            "Example: /sell 0xTokenToSell 1000 2 50 0xTokenToReceive"
        )
        return

    # Parse user inputs
    token_to_sell = args[0]
    try:
        amount_to_sell = float(args[1])  # Token amount to sell
        slippage = float(args[2])  # Slippage percentage
        gas_fees = float(args[3])  # Gas price in gwei
        destination_token = args[4]  # Token to receive
    except ValueError:
        await update.message.reply_text(
            "Invalid input. Ensure amount, slippage, and gas fees are numbers."
        )
        return

    if amount_to_sell <= 0 or slippage <= 0 or gas_fees <= 0:
        await update.message.reply_text(
            "Amount, slippage, and gas fees must be positive values."
        )
        return

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
        # Approve Uniswap to spend the tokens
        token_contract = w3.eth.contract(
            address=w3.to_checksum_address(token_to_sell),
            abi=erc20abi 
        )

        # Convert token amount to smallest unit (wei for tokens)
        decimals = token_contract.functions.decimals().call()
        amount_in_wei = int(amount_to_sell * (10 ** decimals))

        # Approve Uniswap router to spend tokens
        approval_tx = token_contract.functions.approve(
            uniswap_router.address, amount_in_wei
        ).build_transaction({
            "from": sender_address,
            "gas": 50000,
            "gasPrice": Web3.to_wei(gas_fees, "gwei"),
            "nonce": w3.eth.get_transaction_count(sender_address),
        })

        signed_approval_tx = w3.eth.account.sign_transaction(approval_tx, private_key=evm_private_key)
        w3.eth.send_raw_transaction(signed_approval_tx.raw_transaction)

        # Wait for the approval transaction to be mined (optional, but safer)
        await update.message.reply_text("Token approval sent. Processing sell transaction...")

        # Path: Token to sell -> WETH -> Destination token
        path = [
            w3.to_checksum_address(token_to_sell),  # Token you are selling
            w3.to_checksum_address("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"),  # WETH
            w3.to_checksum_address(destination_token),  # Token to receive
        ]

        # Fetch expected output for destination token
        amounts_out = uniswap_router.functions.getAmountsOut(amount_in_wei, path).call()
        min_tokens_out = int(amounts_out[-1] * (1 - slippage / 100))  # Adjust for slippage

        # Create the transaction to sell the tokens
        transaction = uniswap_router.functions.swapExactTokensForTokens(
            amount_in_wei,  # Token amount to sell
            min_tokens_out,  # Minimum tokens to receive
            path,  # Swap path
            w3.to_checksum_address(sender_address),  # Recipient address
            int(time.time()) + 600,  # Deadline
        ).build_transaction({
            "from": sender_address,
            "gas": 200000,  # Gas limit
            "gasPrice": Web3.to_wei(gas_fees, "gwei"),
            "nonce": w3.eth.get_transaction_count(sender_address),
        })

        # Sign and send the transaction
        signed_tx = w3.eth.account.sign_transaction(transaction, private_key=evm_private_key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)

        await update.message.reply_text(
            f"Transaction sent successfully! Tx Hash: {tx_hash.hex()}"
        )

    except Exception as e:
        print(f"Error during sell transaction: {e}")
        await update.message.reply_text(
            "An error occurred while processing your transaction. Please try again."
        )


def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("balance", check_balance))
    application.add_handler(CommandHandler("buy", buy))
    application.add_handler(CommandHandler("sell", sell))
    application.add_handler(CallbackQueryHandler(handle_callbacks))
    application.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))

    print("ApexBT Bot is now running!")
    application.run_polling()


if __name__ == "__main__":
    main()