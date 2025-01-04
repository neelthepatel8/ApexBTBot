from telegram import (
    Update, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton,
    error
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
from decimal import Decimal

import os
import time

from apexbtbot.database import Database
from apexbtbot.wallet import Wallet
from apexbtbot import abi, web3utils, settings

db = Database()
db.init()

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ETH_NODE_URL = os.getenv("ETH_NODE_URL")
UNISWAP_ROUTER_ADDRESS = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D" # mainnet
# UNISWAP_ROUTER_ADDRESS = "0xfff9976782d46cc05630d1f6ebab18b2324d6b14"  # testnet

BUY_TOKEN_ADDRESS, BUY_AMOUNT_CHOICE, BUY_AMOUNT, BUY_CONFIRM = range(4)
SELL_TOKEN_ADDRESS, SELL_DESTINATION_TOKEN, SELL_AMOUNT, SELL_CONFIRM = range(4)

w3 = Web3(Web3.HTTPProvider(ETH_NODE_URL))

uniswap_router = w3.eth.contract(
    address=w3.to_checksum_address(UNISWAP_ROUTER_ADDRESS), abi=abi.uniswap_router
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

    keyboard = [
        [InlineKeyboardButton("💼 Check Balance", callback_data="balance")],
        [InlineKeyboardButton("🛒 Buy Tokens", callback_data="buy_start")],
        [InlineKeyboardButton("💱 Sell Tokens", callback_data="sell_start")],
        [InlineKeyboardButton("❓ Help", callback_data="help")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if wallet:
        await update.message.reply_text(
            f"👋 Welcome back to ApexBT Bot, {user.full_name}!\n\n"
            f"💼 Your Wallet Details:\n"
            f"🔑 EVM Wallet: {wallet['evm_address']}\n"
            f"🔑 Solana Wallet: {wallet['solana_address']} WIP\n\n"
            f"Select an option below to get started:",
            reply_markup=reply_markup,
        )
        return
    else:
        evm_wallet, solana_wallet = await create_wallet_for_user(user_data["id"])
        await update.message.reply_text(
            f"👋 Welcome to ApexBT Bot, {user.full_name}!\n\n"
            f"💼 Your Wallets Have Been Created:\n"
            f"🔑 EVM Wallet: {evm_wallet['address']}\n"
            f"🔑 Solana Wallet: {solana_wallet['address']} WIP\n\n"
            f"Select an option below to get started:",
            reply_markup=reply_markup,
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💼 Check Balance", callback_data="balance")],
        [InlineKeyboardButton("🛒 Buy Tokens", callback_data="buy_start")],
        [InlineKeyboardButton("💱 Sell Tokens", callback_data="sell_start")],
        [InlineKeyboardButton("🔄 Refresh Wallet", callback_data="refresh_wallet")],
        [InlineKeyboardButton("📄 More Help", callback_data="detailed_help")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🛠 **ApexBT Bot Help Menu** 🛠\n\n"
        "Here are the actions you can take:\n\n"
        "💼 **Check Balance**: View your current wallet balances.\n"
        "🛒 **Buy Tokens**: Start a token purchase process.\n"
        "💱 **Sell Tokens**: Start a token sale process.\n"
        "🔄 **Refresh Wallet**: Reload your wallet details.\n"
        "📄 **More Help**: Get detailed usage instructions.\n\n"
        "Select an option below or type `/start` to return to the main menu.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "balance":
        await check_balance(update, context)
        return ConversationHandler.END

    elif query.data == "buy_start":
        return await start_buy_conversation(update, context) 

    elif query.data == "sell_start":
        return await start_sell_conversation(update, context)

    elif query.data == "help":
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=(
                "Here’s how to use the bot:\n\n"
                "💼 **Check Balance**: Use /balance.\n"
                "🛒 **Buy Tokens**: Use /buy <TOKEN_ADDRESS> <AMOUNT> <SLIPPAGE> <GAS_FEES>.\n"
                "💱 **Sell Tokens**: Use /sell <TOKEN_TO_SELL> <AMOUNT> <SLIPPAGE> <GAS_FEES> <DESTINATION_TOKEN>.\n"
            ),
            parse_mode="Markdown"
        )
        return ConversationHandler.END

async def get_user_token_balance(token_address: str, user_id: int, w3: Web3) -> tuple[float, int]:
    try:
        user_data = db.get_user_by_telegram_id(user_id)
        wallet = db.get_wallet_by_user_id(user_data["id"])
        if not wallet:
            return None, None
            
        evm_address = wallet["evm_address"]
        
        token_contract = w3.eth.contract(
            address=w3.to_checksum_address(token_address),
            abi=abi.erc20
        )
        
        decimals = token_contract.functions.decimals().call()
        balance_wei = token_contract.functions.balanceOf(evm_address).call()
        balance_decimal = balance_wei / (10 ** decimals)
        
        return balance_decimal, decimals
        
    except Exception as e:
        print(f"Error fetching token balance: {e}")
        return None, None

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

    try:
        await context.bot.send_message(
            chat_id=user.id,
            text="Your wallet balance is being fetched..."
        )
    except error.Forbidden:
        await update.message.reply_text(
            "I cannot send you private messages. Please start the bot in private chat first."
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
    
async def prompt_for_token(update: Update, operation: str):
    message = f"Enter a token symbol or address to {operation}"
    if update.callback_query:
        await update.callback_query.message.reply_text(message)
    else:
        await update.message.reply_text(message)
    return BUY_TOKEN_ADDRESS if operation == "buy" else SELL_TOKEN_ADDRESS

async def start_buy_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await prompt_for_token(update, "buy")

async def start_sell_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await prompt_for_token(update, "sell")

async def token_not_found(update: Update, operation: str):
    keyboard = [[InlineKeyboardButton("Retry", callback_data=f"retry_{operation}_token_address")]]
    await update.message.reply_text(
        "Token not found.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return BUY_TOKEN_ADDRESS if operation == "buy" else SELL_TOKEN_ADDRESS

async def retry_token_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    operation = query.data.split('_')[1]
    
    if operation == "buy":
        return await start_buy_conversation(update, context)
    else:
        return await start_sell_conversation(update, context)

async def validate_token(token_address, update: Update, operation: str):
    if not Web3.is_address(token_address):
        await token_not_found(update, operation)
        return False
    return True

async def buy_token_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token_address = update.message.text.strip()
    if not await validate_token(token_address, update, "buy"):
        return BUY_TOKEN_ADDRESS

    name, symbol, decimals, price_in_eth = await web3utils.get_token_info(token_address, w3)

    context.user_data["buy_token_address"] = token_address
    context.user_data["buy_token_symbol"] = symbol


    user_data = db.get_user_by_telegram_id(update.effective_user.id)
    wallet = db.get_wallet_by_user_id(user_data["id"])
    evm_address = wallet.get("evm_address")
    eth_balance = Wallet.get_evm_balance(evm_address)

    eth_to_usd = web3utils.fetch_eth_to_usd()
    if eth_to_usd is None:
        await update.message.reply_text(
            "Could not fetch the current ETH/USD price. Try again later."
        )
        return ConversationHandler.END

    price_in_usd = Decimal(price_in_eth) * Decimal(eth_to_usd) if price_in_eth else "N/A"

    keyboard = [
        [
            InlineKeyboardButton("Enter amount in ETH", callback_data="buy_amount_eth"),
            InlineKeyboardButton("Enter amount in USD", callback_data="buy_amount_usd")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Buy ${symbol} -- ({name})\n"
        f"`{token_address}`\n"
        f"[Etherscan ↗](https://etherscan.io/token/{token_address})\n"
        f"Balance: {eth_balance:.4f} ETH\n"
        f"Price: ${price_in_usd:.8f} per token ({price_in_eth:.9f} ETH)\n\n"
        "Please choose how you want to enter the amount below.",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

    return BUY_AMOUNT_CHOICE

async def buy_amount_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    choice = query.data
    context.user_data["buy_amount_type"] = choice
    
    if choice == "buy_amount_eth":
        await query.message.reply_text(
            "Enter the amount in ETH you want to buy",
            parse_mode="Markdown"
        )
    else: 
        await query.message.reply_text(
            "Enter the amount in USD you want to buy",
            parse_mode="Markdown"
        )
    
    return BUY_AMOUNT

async def buy_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
        if amount <= 0:
            raise ValueError("Amount must be positive.")
    except ValueError:
        await update.message.reply_text(
            "Invalid amount."
        )
        return ConversationHandler.END

    token_address = context.user_data["buy_token_address"]
    token_symbol = context.user_data["buy_token_symbol"]
    amount_type = context.user_data["buy_amount_type"]

    try:
        user = update.effective_user
        user_data = db.get_user_by_telegram_id(user.id)
        wallet = db.get_wallet_by_user_id(user_data["id"])
        if not wallet:
            await update.message.reply_text("No wallet found. Use /start first.")
            return ConversationHandler.END
            
        eth_balance = Wallet.get_evm_balance(wallet["evm_address"])

        price_in_eth = await web3utils.get_token_price(token_address, w3)
        if amount_type == "buy_amount_usd":
            eth_price_usd = web3utils.fetch_eth_to_usd()
            eth_amount = amount / eth_price_usd
            token_amount = eth_amount / price_in_eth
        else:
            eth_amount = amount
            token_amount = amount / price_in_eth

        gas_fee = settings.default.gas_fee
        estimated_gas_cost = Web3.to_wei(gas_fee, 'gwei') * 21000
        total_cost = Web3.to_wei(eth_amount, 'ether') + estimated_gas_cost

        if total_cost > eth_balance:
            await update.message.reply_text(
                f"Insufficient balance in your EVM wallet. Please deposit and try again.\n"
                f"Required: {Web3.from_wei(total_cost, 'ether'):.6f} ETH "
                f"(including gas)\n"
                f"Your balance: {Web3.from_wei(eth_balance, 'ether'):.6f} ETH"
            )
            return ConversationHandler.END

        context.user_data.update({
            "buy_amount_eth": eth_amount,
            "buy_amount_tokens": token_amount
        })

        slippage = settings.default.slippage
        keyboard = [
            [
                InlineKeyboardButton("Confirm", callback_data="buy_confirm"),
                InlineKeyboardButton("Cancel", callback_data="cancel")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "**Transaction Preview**\n\n"
            f"You will spend: `{eth_amount:.6f} ETH`\n"
            f"You will receive: `{token_amount:.6f} {token_symbol}`\n"
            f"Token Address: `{token_address}`\n"
            f"Gas Fee: `{gas_fee} gwei`\n"
            f"Slippage: `{slippage}%`\n\n",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
        return BUY_CONFIRM

    except Exception as e:
        print(f"Error calculating token amounts: {e}")
        await update.message.reply_text(
            "Error calculating token amounts. Please try again."
        )
        return BUY_AMOUNT

async def handle_buy_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "buy_confirm":
        return await buy_confirm(update, context)
    elif query.data == "cancel":
        await query.message.reply_text("Transaction cancelled.")
        return ConversationHandler.END

async def buy_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    token_address = context.user_data["buy_token_address"]
    amount_in_eth = context.user_data["buy_amount_eth"]

    slippage = settings.default.gas_fee
    gas_fees = settings.default.slippage

    user = update.effective_user
    user_data = db.get_user_by_telegram_id(user.id)
    wallet = db.get_wallet_by_user_id(user_data["id"])

    evm_private_key = Wallet.decrypt_private_key(wallet["evm_private_key"])
    sender_address = wallet["evm_address"]

    try:
        path = [
            w3.to_checksum_address("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"),  
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
            f"Buy transaction sent successfully!"
            f"Transaction Hash: `{tx_hash.hex()}`"
            f"[View it on Etherscan ↗](https://etherscan.io/tx/{tx_hash.hex()})",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Error during buy transaction: {e}")
        await update.message.reply_text(
            f"An error occurred: {e}"
        )

    return ConversationHandler.END

async def sell_token_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token_address = update.message.text.strip()
    if not await validate_token(token_address, update, "sell"):
        return BUY_TOKEN_ADDRESS
        
    context.user_data["sell_token"] = token_address
    
    balance_decimal, decimals = await get_user_token_balance(
        token_address, 
        update.effective_user.id,
        w3
    )
    
    if balance_decimal is None:
        await update.message.reply_text("No wallet found. Use /start first.")
        return ConversationHandler.END
        
    context.user_data["sell_balance"] = balance_decimal
    await update.message.reply_text(
        f"✅ You have {balance_decimal} tokens for this contract.\n"
        f"How many do you want to sell?",
        parse_mode="Markdown"
    )
    return SELL_AMOUNT

async def sell_destination_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    destination_token = update.message.text.strip()

    if not Web3.is_address(destination_token):
        await update.message.reply_text(
            "❌ The destination token address you provided is invalid. Cancelling the operation."
        )
        return ConversationHandler.END

    context.user_data["destination_token"] = destination_token

    token_to_sell = context.user_data["sell_token"]
    await update.message.reply_text(
        f"✅ Destination token address received!\n"
        f"You want to sell tokens from `{token_to_sell}` to `{destination_token}`.\n"
        f"How many tokens would you like to sell?",
        parse_mode="Markdown"
    )
    return SELL_AMOUNT


async def sell_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
        if amount <= 0:
            raise ValueError("Amount must be positive.")
    except ValueError:
        await update.message.reply_text("Invalid amount. Please enter a positive number.")
        return SELL_AMOUNT

    balance_decimal = context.user_data["sell_balance"]
    if amount > balance_decimal:
        await update.message.reply_text(
            f"You only have {balance_decimal} tokens. Please enter a valid amount."
        )
        return SELL_AMOUNT

    context.user_data["sell_amount"] = amount

    sell_token = context.user_data["sell_token"]
    destination_token = context.user_data["destination_token"]
    await update.message.reply_text(
        f"**Confirm Sell**\n\n"
        f"Token to Sell: `{sell_token}`\n"
        f"Destination Token: `{destination_token}`\n"
        f"Amount: `{amount}`\n\n"
        f"Type 'yes' to confirm or 'no' to cancel.",
        parse_mode="Markdown"
    )
    return SELL_CONFIRM


async def sell_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    if text not in ["yes", "no"]:
        await update.message.reply_text("Please type 'yes' to confirm or 'no' to cancel.")
        return SELL_CONFIRM

    if text == "no":
        await update.message.reply_text("Sell transaction cancelled.")
        return ConversationHandler.END

    token_to_sell = context.user_data["sell_token"]
    destination_token = context.user_data["destination_token"]
    amount_to_sell = context.user_data["sell_amount"]
    slippage = 2.0  
    gas_fees = 10.0 

    user = update.effective_user
    user_data = db.get_user_by_telegram_id(user.id)
    wallet = db.get_wallet_by_user_id(user_data["id"])

    if not wallet:
        await update.message.reply_text("No wallet found. Use /start first.")
        return ConversationHandler.END

    evm_private_key = Wallet.decrypt_private_key(wallet["evm_private_key"])
    sender_address = wallet["evm_address"]

    try:
        token_contract = w3.eth.contract(
            address=w3.to_checksum_address(token_to_sell),
            abi=abi.erc20
        )
        decimals = token_contract.functions.decimals().call()
        amount_in_wei = int(amount_to_sell * (10 ** decimals))

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

        await update.message.reply_text("Approval transaction sent. Processing sell...")

        path = [
            w3.to_checksum_address(token_to_sell),
            w3.to_checksum_address("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"),  # WETH
            w3.to_checksum_address(destination_token),
        ]

        amounts_out = uniswap_router.functions.getAmountsOut(amount_in_wei, path).call()
        min_tokens_out = int(amounts_out[-1] * (1 - slippage / 100))

        transaction = uniswap_router.functions.swapExactTokensForTokens(
            amount_in_wei,
            min_tokens_out,
            path,
            w3.to_checksum_address(sender_address),
            int(time.time()) + 600,
        ).build_transaction({
            "from": sender_address,
            "gas": 200000,
            "gasPrice": Web3.to_wei(gas_fees, "gwei"),
            "nonce": w3.eth.get_transaction_count(sender_address),
        })

        signed_tx = w3.eth.account.sign_transaction(transaction, private_key=evm_private_key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)

        await update.message.reply_text(
            f"Sell transaction sent successfully!\nTx Hash: `{tx_hash.hex()}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Error during sell transaction: {e}")
        await update.message.reply_text(
            f"An error occurred: {e}"
        )

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

async def wallets_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = db.get_user_by_telegram_id(user.id)

    if not user_data:
        await update.message.reply_text(
            "❌ You are not registered. Use /start to register and create your wallets."
        )
        return

    wallet = db.get_wallet_by_user_id(user_data["id"])

    if not wallet:
        await update.message.reply_text(
            "❌ You don't have a wallet. Use /start to create one."
        )
        return

    evm_address = wallet.get("evm_address", "N/A")
    solana_address = wallet.get("solana_address", "N/A")

    await update.message.reply_text(
        f"💼 **Your Wallet Details** 💼\n\n"
        f"🔑 **EVM Wallet**: `{evm_address}`\n"
        f"🔑 **Solana Wallet**: `{solana_address}`\n\n"
        f"Use `/help` to explore available commands.",
        parse_mode="Markdown"
    )
    
def main():
    application = Application.builder().token(BOT_TOKEN).build()


    buy_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_callbacks, pattern="^buy_start$"),
            CommandHandler("buy", start_buy_conversation),
        ],
        states={
            BUY_TOKEN_ADDRESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, buy_token_address),
                CallbackQueryHandler(retry_token_address, pattern="^retry_buy_token_address$")
            ],
            BUY_AMOUNT_CHOICE: [
                CallbackQueryHandler(buy_amount_choice, pattern="^buy_amount_")
            ],
            BUY_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, buy_amount)
            ],
            BUY_CONFIRM: [
                CallbackQueryHandler(handle_buy_confirm, pattern="^(buy_confirm|cancel)$")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )



    sell_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_callbacks, pattern="^sell_start$")],
        states={
            SELL_TOKEN_ADDRESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, sell_token_address),
                CallbackQueryHandler(retry_token_address, pattern="^retry_sell_token_address$")

            ],
            SELL_DESTINATION_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_destination_token)],
            SELL_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_amount)],
            SELL_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_confirm)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )


    application.add_handler(buy_conv_handler)
    application.add_handler(sell_conv_handler)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("wallet", wallets_command))
    application.add_handler(CommandHandler("positions", check_balance))
    application.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(CallbackQueryHandler(handle_callbacks))

    print("ApexBT Bot is now running!")
    application.run_polling()

if __name__ == "__main__":
    main()