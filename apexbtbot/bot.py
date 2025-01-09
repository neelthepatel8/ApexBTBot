from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, error, Message

from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    ChatMemberHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)
from dotenv import load_dotenv
from web3 import Web3, exceptions
from solana.rpc.api import Client
from decimal import Decimal
from datetime import datetime
from io import BytesIO
import os
import time
import qrcode
import base64


from apexbtbot.database import Database
from apexbtbot.wallet import Wallet
from apexbtbot import abi, web3utils, settings, util
from apexbtbot.alchemy import AlchemyAPIWrapper
from apexbtbot.solana import util as solana_utils
from apexbtbot.constants import SOL_DECIMAL
from apexbtbot.solana.functions import _buy, _sell, BuyTokenParams, SellTokenParams
from apexbtbot.solana.fetch import JupiterAggregator, get_amm_v4_pair_from_rpc

db = Database()
db.init()

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ETH_NODE_URL = os.getenv("ETH_NODE_URL")
SOL_NODE_URL = os.getenv("SOL_NODE_URL")

BUY_TOKEN_ADDRESS, BUY_AMOUNT_CHOICE, BUY_AMOUNT, BUY_CONFIRM = range(4)
SELL_TOKEN_ADDRESS, SELL_DESTINATION_TOKEN, SELL_AMOUNT, SELL_CONFIRM = range(4)

SHOWING_ADDRESS = 1

CHAIN_SELECTION = range(100, 101)

SELL_AMOUNT_CHOICE = "SELL_AMOUNT_CHOICE"

alchemy = AlchemyAPIWrapper(ETH_NODE_URL)
radiyum = Client(SOL_NODE_URL)

w3 = Web3(Web3.HTTPProvider(ETH_NODE_URL))
jupiter = JupiterAggregator()

UNISWAP_ROUTER_ADDRESS = "0x2626664c2603336E57B271c5C0b26F421741e481"

uniswap_router = w3.eth.contract(
    address=w3.to_checksum_address(UNISWAP_ROUTER_ADDRESS), abi=abi.uniswap_router
)

main_keyboard = [
    [
        InlineKeyboardButton("Buy", callback_data="buy_start"),
        InlineKeyboardButton("Sell", callback_data="sell_start"),
    ],
    [InlineKeyboardButton("Positions", callback_data="check_balance")],
    [InlineKeyboardButton("Referrals", callback_data="referrals")],
    [
        InlineKeyboardButton("Deposit", callback_data="deposit"),
        InlineKeyboardButton("Withdraw", callback_data="withdraw"),
    ],
    [InlineKeyboardButton("Settings", callback_data="settings")],
    [InlineKeyboardButton("Help", callback_data="help_command")],
]


def _get_keypair_from_user_id(user_id):
    user_data = db.get_user_by_telegram_id(user_id)
    wallet = db.get_wallet_by_user_id(user_data["id"])
    decoded = base64.b64decode(Wallet.decrypt_private_key(wallet["solana_private_key"]))
    keypair = Wallet.get_keypair_from_private_key(decoded)
    return keypair

def buy_sol_chain(update, context):

    # need
    token_address = ""
    slippage = ""
    user = None
    buy_amount = 0

    payer_keypair = _get_keypair_from_user_id(user.id)

    pair_addresses = get_amm_v4_pair_from_rpc(token_address)

    if len(pair_addresses) == 0:
        print("error")
        return

    pair_address = pair_addresses[0]

    _buy(pair_address, payer_keypair, buy_amount, slippage)

def _get_dynamic_context(update: Update):
    if update.callback_query:
        return update.callback_query.from_user, update.callback_query.message

    return update.effective_user, update.message

def _get_dynamic_url(selected_chain: str, token_address=None, tx_hash=None):
    if selected_chain == "base_chain":
        url = f"https://basescan.org" 
        domain = "Basescan"
    else:
        url = f"https://explorer.solana.com"
        domain = "Solscan"
   
    if token_address:
        url += f"/token/{token_address}"

    elif tx_hash:
        url += f"/tx/{tx_hash}" if selected_chain == "base_chain" else f"/tx/0x{tx_hash}"

    return url, domain

async def prompt_chain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, message = _get_dynamic_context(update)

    await message.reply_text(
        "Select a chain to proceed",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Base", callback_data="base_chain"),
                    InlineKeyboardButton("Solana", callback_data="solana_chain"),
                ]
            ]
        ),
    )

    return CHAIN_SELECTION

def register_chain_handlers(application):
    balance_chain_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_callbacks, pattern="^check_balance$"),
            CommandHandler("positions", start_balance_chain_selection),
        ],
        states={
            CHAIN_SELECTION: [
                CallbackQueryHandler(
                    handle_chain_balance, pattern="^(base_chain|solana_chain)$"
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        conversation_timeout=60, 
        allow_reentry=True,
        per_user=True
    )

    buy_chain_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_callbacks, pattern="^buy_start$"),
            CommandHandler("buy", start_buy_chain_selection),
        ],
        states={
            CHAIN_SELECTION: [
                CallbackQueryHandler(
                    handle_chain_buy, pattern="^(base_chain|solana_chain)$"
                )
            ],
            BUY_TOKEN_ADDRESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, buy_token_address),
                CallbackQueryHandler(
                    retry_token_address, pattern="^retry_buy_token_address$"
                ),
            ],
            BUY_AMOUNT_CHOICE: [
                CallbackQueryHandler(buy_amount_choice, pattern="^buy_amount_")
            ],
            BUY_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, buy_amount)],
            BUY_CONFIRM: [
                CallbackQueryHandler(
                    handle_buy_confirm, pattern="^(buy_confirm|cancel)$"
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        conversation_timeout=60, 
        allow_reentry=True,
        per_user=True
    )

    sell_chain_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_callbacks, pattern="^sell_start$"),
            CommandHandler("sell", start_sell_chain_selection),
        ],
        states={
            CHAIN_SELECTION: [
                CallbackQueryHandler(
                    handle_chain_sell, pattern="^(base_chain|solana_chain)$"
                )
            ],
            SELL_TOKEN_ADDRESS: [
                CallbackQueryHandler(
                    sell_token_address,
                    pattern="^(base_chain|solana_chain)$"
                ),
                CallbackQueryHandler(
                    sell_token_selected,
                    pattern="^sell_[0-9]+$"
                ),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            SELL_AMOUNT_CHOICE: [
                CallbackQueryHandler(
                    handle_sell_amount_selection, pattern="^amt_(custom|[0-9]+)$"
                ),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            SELL_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, sell_amount),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            SELL_CONFIRM: [
                CallbackQueryHandler(sell_confirm, pattern="^(confirm_sell|cancel)$")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        conversation_timeout=60, 
        allow_reentry=True,
        per_user=True
    )

    application.add_handler(balance_chain_handler)
    application.add_handler(buy_chain_handler)
    application.add_handler(sell_chain_handler)

async def start_balance_chain_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["command_type"] = "balance"
    return await prompt_chain(update, context)

async def start_buy_chain_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["command_type"] = "buy"
    return await prompt_chain(update, context)

async def start_sell_chain_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["command_type"] = "sell"
    return await prompt_chain(update, context)

async def start_deposit_chain_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["command_type"] = "deposit"
    return await prompt_chain(update, context)

async def handle_chain_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected_chain = query.data
    user, _ = _get_dynamic_context(update)
    db_user = db.get_user_by_telegram_id(user.id)
    wallet = db.get_wallet_by_user_id(db_user["id"])

    if not wallet:
        await no_wallet(update, context)
        return ConversationHandler.END

    await query.message.edit_text("Fetching balance...")

    try:
        if selected_chain == "base_chain":
            wallet_address = db.get_wallet_address_by_user_id(db_user["id"])
            balance_message = Wallet.build_evm_balance_string(wallet_address)
        else:
            wallet_address = db.get_wallet_address_by_user_id(
                db_user["id"], chain="solana"
            )
            balance_message = Wallet.build_solana_balance_string(wallet_address)

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        balance_message += f"\n\n<i>Last fetched at: {timestamp}</i>"

        await query.message.edit_text(balance_message, parse_mode="HTML")
    except Exception as e:
        await query.message.edit_text(f"Error fetching balance: {e}")
        print(f"Error fetching balance: {e}")

    return ConversationHandler.END

async def no_wallet(update, context):
    _, message = _get_dynamic_context(update)
    await message.reply_text("No wallet found. Use /start first.")
    return ConversationHandler.END

async def handle_chain_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    selected_chain = query.data
    context.user_data["selected_chain"] = selected_chain

    await query.message.edit_text("Enter the token address you want to buy:")
    return BUY_TOKEN_ADDRESS

async def handle_chain_sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    selected_chain = query.data
    context.user_data["selected_chain"] = selected_chain

    return await sell_token_address(update, context)

def register_deposit_handlers(application):
    deposit_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_callbacks, pattern="^deposit$"),
            CommandHandler("deposit", start_deposit_chain_selection),
        ],
        states={
            CHAIN_SELECTION: [
                CallbackQueryHandler(
                    handle_chain_deposit, pattern="^(base_chain|solana_chain)$"
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(deposit_handler)

async def handle_chain_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected_chain = query.data
    user = query.from_user
    user_data = db.get_user_by_telegram_id(user.id)
    wallet = db.get_wallet_by_user_id(user_data["id"])

    if not wallet:
        await no_wallet(update, context)
        return ConversationHandler.END

    keyboard = [
        [
            InlineKeyboardButton("Show QR Code", callback_data="show_qr"),
            InlineKeyboardButton("Check Balance", callback_data="check_balance"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    token_name, wallet_address, network_name, chain_id = range(4)

    if selected_chain == "base_chain":
        token_name = "ETH"
        wallet_address = wallet["evm_address"]
        network_name = "Base"
        chain_id = 8453
    else:
        token_name = "SOL"
        wallet_address = wallet["solana_address"]
        network_name = "Solana"
        chain_id = 101

    context.user_data["wallet_address"] = wallet_address

    message = (
        "📥 *Deposit Funds*\n\n"
        f"To deposit funds, send {token_name} to:\n`{wallet_address}`\n\n"
        f"*Supported Networks:*\n• {network_name} Network (Chain ID: {chain_id})\n\n"
        "⚠️ *Important:*\n"
        f"• Only send tokens on {network_name} network\n"
        f"• Minimum deposit: 0.01 {token_name} or equivalent\n"
        "• Deposits confirm in 1-2 minutes\n\n"
        "Click 'Check Balance' after sending to verify your deposit."
    )

    await query.message.edit_text(
        message, parse_mode="Markdown", reply_markup=reply_markup
    )
    return ConversationHandler.END

async def show_qr_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()

        user = query.from_user
        user_data = db.get_user_by_telegram_id(user.id)

        wallet_address = context.user_data["wallet_address"]

        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(wallet_address)
        qr.make(fit=True)

        img_buffer = BytesIO()
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(img_buffer, format="PNG")
        img_buffer.seek(0)

        caption = (
            "Scan this QR code to get your deposit address\n"
            f"Address: `{wallet_address}`"
        )

        await query.message.reply_photo(
            photo=img_buffer, caption=caption, parse_mode="Markdown"
        )

    except Exception as e:
        print(f"Error generating QR code: {e}")
        await query.message.reply_text(
            "Sorry, there was an error generating the QR code. Please use the address provided above."
        )

async def check_deposit_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()

        user = query.from_user
        user_data = db.get_user_by_telegram_id(user.id)
        wallet_address = db.get_wallet_address_by_user_id(user_data["id"])

        balance_message = Wallet.build_evm_balance_string(wallet_address)

        keyboard = [
            [InlineKeyboardButton("🔄 Refresh Balance", callback_data="check_balance")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.reply_text(
            f"*Current Balance:*\n\n{balance_message}",
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )

    except Exception as e:
        print(f"Error checking balance: {e}")
        await query.message.reply_text(
            "Sorry, there was an error checking your balance. Please try again later."
        )

def register_withdraw_handlers(application):
    withdraw_handler = CommandHandler("withdraw", withdraw_start)
    application.add_handler(withdraw_handler)

async def withdraw_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        user = update.callback_query.from_user
        message = update.callback_query.message
    else:
        user = update.effective_user
        message = update.message
    try:
        user_data = db.get_user_by_telegram_id(user.id)
        wallet = db.get_wallet_by_user_id(user_data["id"])

        private_key = Wallet.decrypt_private_key(wallet["evm_private_key"])
        if not private_key:
            await message.reply_text(
                "❌ Sorry, we couldn't retrieve your private key at this time. Please try again later.",
                parse_mode="Markdown",
            )
            return ConversationHandler.END

        await message.reply_text(
            f"📤 *Withdraw ETH*\n\n"
            f"Your wallet address: `{wallet['evm_address']}`\n\n"
            f"🔑 *Private Key:* `{private_key}`\n\n"
            "You can use this private key in any Web3 wallet (e.g., MetaMask, Trust Wallet) "
            "to access and withdraw your funds.\n\n",
            parse_mode="Markdown",
        )

        return ConversationHandler.END

    except Exception as e:
        print(f"Error in withdraw_start: {e}")
        await update.message.reply_text(
            "Sorry, there was an error processing your request. Please try again later."
        )
        return ConversationHandler.END

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = db.get_user_by_telegram_id(user.id)
    reply_markup = InlineKeyboardMarkup(main_keyboard)


    if not user_data:
        db.add_user(user.id, user.full_name)
        user_data = db.get_user_by_telegram_id(user.id)
        await update.message.reply_text("New user detected, creating wallets and account...")

    wallet = db.get_wallet_by_user_id(user_data["id"])

    await update.message.reply_text("Please wait while I gather your information...")

    if wallet:
        try:
            evm_balance_string = Wallet.build_evm_balance_string(wallet["evm_address"])
            sol_balance_string = Wallet.build_solana_balance_string(
                wallet["solana_address"]
            )
            await update.message.reply_text(
                f"<b>Welcome back to ApexBT Bot, {user.full_name}!</b>\n\n"
                f"<u>Your Wallet Details:</u>\n"
                f"🔑 <b>EVM Wallet:</b> <code>{wallet['evm_address']}</code> (Tap to copy)\n"
                f"\n\n{evm_balance_string}\n\n"
                f"🔑 <b>Solana Wallet:</b> <code>{wallet['solana_address']}</code> (Tap to copy)"
                f"\n\n{sol_balance_string}\n\n"
                f"",
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        except Exception as e:
            await update.message.reply_text(
                f"<b>Welcome back to ApexBT Bot, {user.full_name}!</b>\n\n"
                f"<u>Your Wallet Details:</u>\n"
                f"🔑 <b>EVM Wallet:</b> <code>{wallet['evm_address']}</code> (Tap to copy)\n"
                f"🔑 <b>Solana Wallet:</b> <code>{wallet['solana_address']}</code> (Tap to copy)\n\n"
                f"⚠️ Balance information temporarily unavailable",
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
    else:
        try:
            evm_wallet, solana_wallet = await create_wallet_for_user(user_data["id"])

            await update.message.reply_text(
                f"<b>Welcome to ApexBT Bot, {user.full_name}!</b>\n\n"
                f"<u>Your New Wallets Have Been Created:</u>\n"
                f"🔑 <b>EVM Wallet:</b> <code>{evm_wallet['address']}</code> (Tap to copy)\n"
                f"🔑 <b>Solana Wallet:</b> <code>{solana_wallet['address']}</code> (Tap to copy)\n\n"
                f"✨ Your wallets are ready to use! You can now:\n"
                f"• Deposit funds\n"
                f"• Check balances\n"
                f"• Start trading",
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        except Exception as e:
            await update.message.reply_text(
                f"I cannot send you private messages, please initiate a conversation with me. {e}",
                parse_mode="HTML",
            )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    reply_markup = InlineKeyboardMarkup(main_keyboard)

    await update.callback_query.message.reply_text(
        "ApexBT Bot Help Menu\n\n"
        "Here are the actions you can take:\n\n"
        "**Check Positions**: View your current wallet balances.\n"
        "**Buy Tokens**: Start a token purchase process.\n"
        "**Sell Tokens**: Start a token sale process.\n"
        "**Refresh Wallet**: Reload your wallet details.\n"
        "**More Help**: Get detailed usage instructions.\n\n"
        "Select an option below or type `/start` to return to the main menu.",
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "check_balance":
        await start_balance_chain_selection(update, context)
        return ConversationHandler.END

    elif query.data == "buy_start":
        return await start_buy_chain_selection(update, context)

    elif query.data == "sell_start":
        return await start_sell_chain_selection(update, context)

    elif query.data == "deposit":
        return await start_deposit_chain_selection(update, context)

    elif query.data == "withdraw":
        return await withdraw_start(update, context)

    elif query.data == "show_qr":
        return await show_qr_code(update, context)

    elif query.data in ["base_chain", "solana_chain"]:
        command_type = context.user_data.get("command_type")

        if command_type == "balance":
            return await handle_chain_balance(update, context)

        elif command_type == "deposit":
            return await handle_chain_deposit(update, context)

    elif query.data == "help":
        await help_command(update, context)
        return ConversationHandler.END

async def prompt_for_token(update: Update, operation: str):
    message = f"Enter a token address to {operation}"
    if update.callback_query:
        await update.callback_query.message.reply_text(message)
    else:
        await update.message.reply_text(message)
    return BUY_TOKEN_ADDRESS if operation == "buy" else SELL_TOKEN_ADDRESS

async def start_buy_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await prompt_for_token(update, "buy")

async def token_not_found(message, operation: str):
    keyboard = [
        [
            InlineKeyboardButton(
                "Retry", callback_data=f"retry_{operation}_token_address"
            )
        ]
    ]
    await message.reply_text(
        "Token not found.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return BUY_TOKEN_ADDRESS if operation == "buy" else SELL_TOKEN_ADDRESS

async def retry_token_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    operation = query.data.split("_")[1]

    if operation == "buy":
        return await start_buy_conversation(update, context)
    else:
        return await start_sell_conversation(update, context)

async def validate_token(token_address, message, operation: str):
    if not Web3.is_address(token_address):
        await token_not_found(message, operation)
        return False
    return True

async def buy_token_address(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user, message = _get_dynamic_context(update)
    token_address = update.message.text.strip()
    selected_chain = context.user_data.get("selected_chain")

    user_data = db.get_user_by_telegram_id(user.id)
    wallet = db.get_wallet_by_user_id(user_data["id"])

    if selected_chain == "base_chain":
        name, symbol, decimals, price_in_eth, eth_balance, price_in_usd, keyboard = (
            await _buy_token_address_evm(token_address, wallet, message)
        )

    elif selected_chain == "solana_chain":
        name, symbol, decimals, price_in_sol, sol_balance, price_in_usd, keyboard = (
            await _buy_token_address_sol(token_address, wallet, message)
        )

    context.user_data["buy_token_address"] = token_address
    context.user_data["buy_token_symbol"] = symbol
    context.user_data["buy_token_decimals"] = decimals
    context.user_data["buy_token_price_in_native"] = (
        price_in_eth if selected_chain == "base_chain" else price_in_sol
    )
    context.user_data["buy_token_price_in_usd"] = price_in_usd

    reply_markup = InlineKeyboardMarkup(keyboard)

    explorer_link = (
        f"https://basescan.org/token/{token_address}"
        if selected_chain == "base_chain"
        else f"https://solscan.io/token/{token_address}"
    )

    balance_text = (
        f"{eth_balance:.4f} ETH"
        if selected_chain == "base_chain"
        else f"{sol_balance:.4f} SOL"
    )

    price_text = (
        f"${price_in_usd:.8f} per token ({price_in_eth:.9f} ETH)"
        if selected_chain == "base_chain"
        else f"${price_in_usd:.8f} per token ({price_in_sol:.9f} SOL)"
    )

    url_name = "Basescan" if selected_chain == "base_chain" else "Solscan"
    await message.reply_text(
        f"Buy ${symbol} -- ({name})\n"
        f"`{token_address}`\n"
        f"[{url_name} ↗]({explorer_link})"
        f"\n\nYour balance: {balance_text}\n"
        f"Price: {price_text}",
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )

    return BUY_AMOUNT_CHOICE

async def _buy_token_address_sol(token_address, wallet, message):
    name, symbol, decimals, price_in_sol, price_in_usd = solana_utils.get_token_info(
        token_address
    )

    if not name:
        await message.reply_text("Token not found, please try again.")
        return ConversationHandler.END

    sol_balance = Wallet.get_solana_balance(wallet["solana_address"])

    keyboard = [
        [
            InlineKeyboardButton(
                "Enter amount (in SOL)", callback_data="buy_amount_sol"
            ),
        ]
    ]

    return name, symbol, decimals, price_in_sol, sol_balance, price_in_usd, keyboard

async def _buy_token_address_evm(token_address, wallet, message):
    if not await validate_token(token_address, message, "buy"):
        return BUY_TOKEN_ADDRESS

    name, symbol, decimals, price_in_eth = await web3utils.get_token_info(
        token_address, w3
    )

    price_in_eth = 1 / price_in_eth
    eth_balance = Wallet.get_evm_balance(wallet["evm_address"])

    eth_to_usd = web3utils.fetch_eth_to_usd()
    if eth_to_usd is None:
        await message.reply_text(
            "Could not fetch the current ETH/USD price. Try again later."
        )
        return ConversationHandler.END

    price_in_usd = (
        Decimal(price_in_eth) * Decimal(eth_to_usd) if price_in_eth else "N/A"
    )

    print(f"{price_in_eth=} {price_in_usd=}")

    keyboard = [
        [
            InlineKeyboardButton(
                "Enter amount (in ETH)", callback_data="buy_amount_eth"
            ),
        ]
    ]

    return name, symbol, decimals, price_in_eth, eth_balance, price_in_usd, keyboard

async def buy_amount_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    choice = query.data
    context.user_data["buy_amount_type"] = choice

    if choice == "buy_amount_eth":
        await query.message.reply_text(
            "Enter the amount in ETH you want to buy", parse_mode="Markdown"
        )
    else:
        await query.message.reply_text(
            "Enter the amount in SOL you want to buy", parse_mode="Markdown"
        )

    return BUY_AMOUNT

async def buy_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, message = _get_dynamic_context(update)
    selected_chain = context.user_data.get("selected_chain")

    try:
        amount = float(update.message.text.strip())
        if amount <= 0:
            raise ValueError("Amount must be positive.")
    except ValueError:
        await update.message.reply_text("Invalid amount.")
        return ConversationHandler.END

    token_address = context.user_data["buy_token_address"]
    token_symbol = context.user_data["buy_token_symbol"]
    price_in_native = context.user_data["buy_token_price_in_native"]
    price_in_usd = float(context.user_data["buy_token_price_in_usd"])

    value_in_usd = float(price_in_usd) * amount

    try:
        user_data = db.get_user_by_telegram_id(user.id)
        wallet = db.get_wallet_by_user_id(user_data["id"])
        if not wallet:
            await no_wallet(update, context)
            return ConversationHandler.END

        wallet_address = (
            wallet["evm_address"]
            if selected_chain == "base_chain"
            else wallet["solana_address"]
        )

        balance = (
            Wallet.get_evm_balance(wallet_address)
            if selected_chain == "base_chain"
            else Wallet.get_solana_balance(wallet_address)
        )

        token_amount = amount / float(price_in_native)

        if selected_chain == "base_chain":
            gas_fee = settings.default.base.gas_fee

            estimated_gas_cost = Web3.to_wei(gas_fee, "gwei") * 21000

            total_cost = Web3.to_wei(price_in_native, "ether") + estimated_gas_cost

            if Web3.from_wei(total_cost, "ether") > balance:
                await update.message.reply_text(
                    f"Insufficient balance in your EVM wallet. Please deposit and try again.\n"
                    f"Required: {Web3.from_wei(total_cost, 'ether'):.6f} ETH "
                    f"(including gas)\n"
                    f"Your balance: {balance:.6f} ETH"
                )
                return ConversationHandler.END

        else:
            gas_fee = 0.0001
            unit_budget = settings.default.sol.unit_budget
            unit_price = settings.default.sol.unit_price
            max_gas_fee = unit_budget * unit_price
            max_gas_fee_sol = max_gas_fee / SOL_DECIMAL

            rent_exemption = 0.00203928

            total_cost = price_in_native + max_gas_fee_sol + rent_exemption

            if total_cost > balance:
                await update.message.reply_text(
                    f"Insufficient balance in your Solana wallet. Please deposit and try again.\n"
                    f"Required: {total_cost:.6f} SOL "
                    f"(including max gas fee of {max_gas_fee_sol:.6f} SOL and rent of {rent_exemption} SOL)\n"
                    f"Your balance: {balance:.6f} SOL"
                )
                return ConversationHandler.END

        context.user_data.update(
            {"buy_amount_native": amount, "buy_amount_tokens": token_amount}
        )

        slippage = settings.default.base.slippage
        keyboard = [
            [
                InlineKeyboardButton("Confirm", callback_data="buy_confirm"),
                InlineKeyboardButton("Cancel", callback_data="cancel"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        gas_fee_unit = "gwei" if selected_chain == "base_chain" else "SOL"
        await message.reply_text(
            "**Transaction Preview**\n\n"
            f"You will spend: `{amount:.6f} {'ETH' if selected_chain == 'base_chain' else 'SOL'} (${token_amount * price_in_usd:.2f})`\n"
            f"You will receive: `{token_amount:.6f} {token_symbol}`\n"
            f"Token Address: `{token_address}`\n"
            f"Gas Fee: `{gas_fee} {gas_fee_unit}`\n"
            f"Slippage: `{slippage}%`\n\n",
            parse_mode="Markdown",
            reply_markup=reply_markup,
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

    user, message = _get_dynamic_context(update)
    selected_chain = context.user_data.get("selected_chain")

    token_address = context.user_data["buy_token_address"]
    token_symbol = context.user_data["buy_token_symbol"]
    token_decimals = context.user_data["buy_token_decimals"]
    amount_in_native = context.user_data["buy_amount_native"]
    amount_in_token = context.user_data["buy_amount_tokens"]

    user_data = db.get_user_by_telegram_id(user.id)
    wallet = db.get_wallet_by_user_id(user_data["id"])

    keyboard = [
        [
            InlineKeyboardButton(
                text="View your Positions", callback_data="check_balance"
            )
        ]
    ]

    await message.reply_text("Sending transaction now...")

    if selected_chain == "base_chain":
        tx_hash = await _buy_confirm_evm(
            token_address,
            token_decimals,
            token_symbol,
            amount_in_native,
            wallet,
            message,
            keyboard,
        )
        origin_domain = "basescan.org"

    else:
        tx_hash = await _buy_confirm_sol(
            token_address, wallet, message, amount_in_native
        )
        print("Exited")
        origin_domain = "explorer.solana.com"

    if not tx_hash:
        await message.reply_text("Router currently busy, please try again later.")
        return ConversationHandler.END

    url = f"https://{origin_domain}/tx/0x{tx_hash}"
    await message.reply(
        f"Buy transaction sent successfully!\n"
        f"Amount Bought: {amount_in_token:.6f} {token_symbol} ({amount_in_native:.4f} {'ETH' if selected_chain == 'base_chain' else 'SOL'})\n"
        f"Transaction Hash: `{tx_hash}`\n"
        f"[View it on {'Base' if selected_chain == 'base_chain' else 'Sol'}scan ↗]({url})",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def _buy_confirm_sol(token_address, wallet, message, amount_in_native):
    buy_params = BuyTokenParams(
        private_key=Wallet.decrypt_private_key(wallet["solana_private_key"]),
        token_mint=token_address,  
        sol_amount=amount_in_native,
    )
    
    txid = await _buy(buy_params)

    print("Recieved txid in bot: ", txid)
    return txid

async def _buy_confirm_evm(
    token_address,
    token_decimals,
    token_symbol,
    amount_in_native,
    wallet,
    message,
    keyboard,
):

    slippage = settings.default.base.gas_fee

    evm_private_key = Wallet.decrypt_private_key(wallet["evm_private_key"])
    sender_address = wallet["evm_address"]

    try:
        current_gas_price = w3.eth.gas_price
        gas_price = int(current_gas_price * 1.2)

        weth_address = "0x4200000000000000000000000000000000000006"

        pool_address, fee_tier = await web3utils.get_pair_address(token_address, w3)

        amount_in_wei = Web3.to_wei(amount_in_native, "ether")

        quoter = w3.eth.contract(
            address=w3.to_checksum_address(
                "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"
            ),
            abi=abi.uniswap_quote,
        )

        quote_params = (weth_address, token_address, amount_in_wei, fee_tier, 0)

        result = quoter.functions.quoteExactInputSingle(quote_params).call()
        amount_out = result[0]
        min_tokens_out = int(amount_out * (1 - slippage / 100))

        nonce = w3.eth.get_transaction_count(sender_address, "latest")

        router = w3.eth.contract(
            address=w3.to_checksum_address(
                "0x2626664c2603336E57B271c5C0b26F421741e481"
            ),
            abi=abi.uniswap_router,
        )

        params = {
            "tokenIn": weth_address,
            "tokenOut": token_address,
            "fee": fee_tier,
            "recipient": sender_address,
            "deadline": int(time.time()) + 600,
            "amountIn": amount_in_wei,
            "amountOutMinimum": min_tokens_out,
            "sqrtPriceLimitX96": 0,
        }

        transaction = router.functions.exactInputSingle(params).build_transaction(
            {
                "from": sender_address,
                "value": amount_in_wei,
                "gas": 500000,
                "gasPrice": gas_price,
                "nonce": nonce,
            }
        )

        signed_tx = w3.eth.account.sign_transaction(
            transaction, private_key=evm_private_key
        )
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)

        return tx_hash.hex()

    except exceptions.Web3RPCError as e:
        if "replacement transaction underpriced" in str(e):
            try:
                gas_price = int(current_gas_price * 1.5)
                transaction["gasPrice"] = gas_price
                signed_tx = w3.eth.account.sign_transaction(
                    transaction, private_key=evm_private_key
                )
                tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                return tx_hash
            except Exception as retry_e:
                await message.reply_text(
                    f"Failed to send transaction even with higher gas: {str(retry_e)}"
                )
        else:
            await message.reply_text(f"An error occurred: {str(e)}")
    except Exception as e:
        print(f"Error during buy transaction: {e}")
        await message.reply_text(f"An error occurred: {str(e)}")

    return ConversationHandler.END

async def start_sell_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await prompt_for_token(update, "sell")

async def sell_token_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user, message = _get_dynamic_context(update)
    user_data = db.get_user_by_telegram_id(user.id)
    wallet = db.get_wallet_by_user_id(user_data["id"])
    selected_chain = context.user_data.get("selected_chain")
    wallet_address = wallet['evm_address' if selected_chain == "base_chain" else 'solana_address']


    try:
        loading_message = await message.reply_text(
            "Fetching your token balances, please wait... ⏳", parse_mode="HTML"
        )

        if selected_chain == "base_chain":
            token_balances = Wallet.get_evm_token_balances(wallet_address)

        else:
            token_balances = Wallet.get_solana_token_balances(wallet_address)

        context.user_data["token_data"] = {}
        message_parts = ["Select a token to sell:\n"]
        keyboard = []

        for token_address, data in token_balances.items():
            balance = data["balance"]
            symbol = data["symbol"]
            price_in_usd = data["price_in_usd"]
            value_in_usd = data["value_in_usd"]
            name = data["name"]

            if symbol in ["ETH", "SOL"]:
                continue

            if balance > 0:
                token_id = len(context.user_data["token_data"])
                context.user_data["token_data"][str(token_id)] = {
                    "symbol": symbol,
                    "address": token_address,
                    "name": name,
                    "balance": balance,
                    "price_in_usd": price_in_usd,
                    "value_in_usd": value_in_usd,
                }
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"Sell {symbol} ({balance:.4f})",
                            callback_data=f"sell_{token_id}",
                        )
                    ]
                )

        if selected_chain == "base_chain":
            balance_string = Wallet.build_evm_balance_string(
                wallet_address, no_title=True, no_eth=True
            )

        else:
            balance_string = Wallet.build_solana_balance_string(
                wallet_address, no_title=True, no_sol=True
            )

        message_parts.append(balance_string)
        keyboard.append([InlineKeyboardButton("Cancel", callback_data="cancel")])

        if len(keyboard) == 1:
            await loading_message.edit_text(
                "You don't have any tokens to sell.", parse_mode="Markdown"
            )
            return ConversationHandler.END

        reply_markup = InlineKeyboardMarkup(keyboard)
        await loading_message.edit_text(
            "\n".join(message_parts), reply_markup=reply_markup, parse_mode="HTML"
        )

        return SELL_TOKEN_ADDRESS

    except Exception as e:
        print(f"Error in start_sell_conversation: {e}")
        await message.reply_text(
            "Sorry, there was an error fetching your balances. Please try again later."
        )
        return ConversationHandler.END

async def sell_token_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    selected_chain = context.user_data.get("selected_chain")

    token_id = query.data.split("_")[1]
    token_data = context.user_data["token_data"][token_id]
    symbol = token_data["symbol"]
    address = token_data["address"]
    balance = token_data["balance"]
    token_price_usd = token_data["price_in_usd"]
    token_name = token_data["name"]

    context.user_data["sell_token_symbol"] = symbol
    context.user_data["sell_token_address"] = address
    context.user_data["sell_token_balance"] = balance
    context.user_data["sell_token_price"] = token_price_usd
    context.user_data["sell_token_name"] = token_name

    keyboard = [
        [
            InlineKeyboardButton("25%", callback_data=f"amt_25"),
            InlineKeyboardButton("50%", callback_data=f"amt_50"),
            InlineKeyboardButton("75%", callback_data=f"amt_75"),
        ],
        [InlineKeyboardButton("100% (Max)", callback_data=f"amt_100")],
        [InlineKeyboardButton("Custom Amount", callback_data=f"amt_custom")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    url, domain = _get_dynamic_url(selected_chain)
    message = (
        f"Sell ${symbol} - {token_name}\n\n"
        f"`{address}`\n"
        f"[{domain} ↗]({url})\n"
        f"\nYour Balance: {balance} {symbol}\n"
        f"Price: ${token_price_usd:.4f}\n"
        "Select an amount to sell"
    )

    await query.message.reply_text(
        message, reply_markup=reply_markup, parse_mode="Markdown"
    )

    return SELL_AMOUNT_CHOICE

async def handle_sell_amount_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    amount_type = query.data.split("_")[1]
    balance = context.user_data["sell_token_balance"]

    if amount_type == "custom":
        await query.message.reply_text(
            f"Enter thae amount you want to sell (max {balance:.4f}):"
        )
        return SELL_AMOUNT

    percentage = int(amount_type)
    sell_amount = (percentage / 100) * balance
    context.user_data["sell_amount"] = sell_amount

    return await show_sell_confirmation(update, context)

async def show_sell_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    selected_chain = context.user_data.get("selected_chain")

    symbol = context.user_data["sell_token_symbol"]
    amount = context.user_data["sell_amount"]
    price_in_usd = context.user_data["sell_token_price"]
    name = context.user_data["sell_token_name"]
    value_usd = price_in_usd * amount

    if selected_chain == "base_chain":
        eth_price_usd = alchemy.get_eth_price()
        token_price_native = value_usd / eth_price_usd
    else:
        sol_price_usd = solana_utils.get_sol_price()
        token_price_native = value_usd / sol_price_usd

    
    message = (
        f"*Confirm Sell Order*\n\n"
        f"Token: ${symbol} - ({name})\n"
        f"Amount: {amount:.4f}\n"
        f"Value: ${value_usd:.4f}\n"
        f"Price per token: ${price_in_usd:.4f}\n\n"
        f"You will receive {token_price_native:.6f} {'ETH' if selected_chain == 'base_chain' else 'SOL'}\n"
    )

    keyboard = [
        [
            InlineKeyboardButton("Confirm", callback_data="confirm_sell"),
            InlineKeyboardButton("Cancel", callback_data="cancel"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.reply_text(
        message, reply_markup=reply_markup, parse_mode="Markdown"
    )

    return SELL_CONFIRM

async def sell_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.lower()
        balance = context.user_data["sell_token_balance"]
        symbol = context.user_data["sell_token_symbol"]
        address = context.user_data["sell_token_address"]

        if text == "max":
            amount = balance
        else:
            try:
                amount = float(text)
            except ValueError:
                await update.message.reply_text(f"Please enter a valid number or 'max'")
                return SELL_AMOUNT

        if amount <= 0:
            await update.message.reply_text("Amount must be greater than 0")
            return SELL_AMOUNT

        if amount > balance:
            await update.message.reply_text(
                f"Amount exceeds your balance of {balance:.4f} {symbol}"
            )
            return SELL_AMOUNT

        context.user_data["sell_amount"] = amount

        eth_price_usd = web3utils.fetch_eth_to_usd()
        name, symbol, decimals, price_in_eth = await web3utils.get_token_info(
            address, w3
        )

        if address.lower() == "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913".lower():
            token_price_usd = 1.0
            value_usd = amount
        else:
            token_price_usd = float(price_in_eth) * eth_price_usd
            value_usd = amount * token_price_usd

        message = (
            f"*Confirm Sell Order*\n\n"
            f"Token: {symbol}\n"
            f"Amount: {amount:.4f}\n"
            f"Value: ${value_usd:.2f}\n"
            f"Price per token: ${token_price_usd:.4f}\n\n"
            f"You will receive ETH\n"
            "Slippage: 2%\n\n"
            "Do you want to proceed?"
        )

        keyboard = [
            [
                InlineKeyboardButton("Confirm", callback_data="confirm_sell"),
                InlineKeyboardButton("Cancel", callback_data="cancel"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            message, reply_markup=reply_markup, parse_mode="Markdown"
        )

        return SELL_CONFIRM

    except Exception as e:
        print(f"Error in sell_amount: {e}")
        await update.message.reply_text(
            "An error occurred. Please try again or use /cancel to start over."
        )
        return SELL_AMOUNT

async def sell_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.message.reply_text("Sell transaction cancelled.")
        return ConversationHandler.END
    
    user = query.from_user
    user_data = db.get_user_by_telegram_id(user.id)
    wallet = db.get_wallet_by_user_id(user_data["id"])

    token_address = context.user_data["sell_token_address"]
    amount_to_sell = context.user_data["sell_amount"]

    if not wallet:
        await no_wallet(update, context)
        return ConversationHandler.END
    
    selected_chain = context.user_data.get("selected_chain")

    status_message = await query.message.reply_text("Checking token approval and sending transaction...")


    if selected_chain == "base_chain":
        tx_hash = await _sell_confirm_eth(token_address, amount_to_sell, wallet)    
    else:
        tx_hash = await _sell_confirm_sol(token_address, amount_to_sell, wallet)
    
    
    keyboard_balance = [
            [InlineKeyboardButton(text="Check Balance", callback_data="check_balance")]
        ]
    
    url, domain = _get_dynamic_url(selected_chain, tx_hash=tx_hash)
    success_message = (
            "✅ *Sell Transaction Sent!*\n\n"
            f"*Amount:* {amount_to_sell:.4f} {context.user_data['sell_token_symbol']}\n"
            f"*Transaction Hash:* `{tx_hash}`\n\n"
            f"[View on {domain} ↗]({url})"
        )
    
    
    await status_message.edit_text(
        success_message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard_balance),
    )

    return ConversationHandler.END

async def _sell_confirm_eth(token_address, amount_to_sell, wallet):
    token_address = Web3.to_checksum_address(token_address)
    slippage = settings.default.base.slippage
    sender_address = wallet["evm_address"]
    evm_private_key = Wallet.decrypt_private_key(wallet["evm_private_key"])
    
    router_address = Web3.to_checksum_address("0x2626664c2603336E57B271c5C0b26F421741e481")
    weth_address = Web3.to_checksum_address("0x4200000000000000000000000000000000000006")
    
    token_contract = w3.eth.contract(address=token_address, abi=abi.erc20)
    decimals = token_contract.functions.decimals().call()
    amount_in_wei = int(amount_to_sell * (10**decimals))
    
    # Check balance first
    token_balance = token_contract.functions.balanceOf(sender_address).call()
    if amount_in_wei > token_balance:
        amount_in_wei = token_balance
        amount_to_sell = amount_in_wei / (10**decimals)
        print(f"Adjusted to maximum available balance: {amount_in_wei}")
    
    # Check allowance and approve if needed
    current_allowance = token_contract.functions.allowance(sender_address, router_address).call()
    if current_allowance < amount_in_wei:
        gas_price = w3.eth.gas_price
        max_uint = 2**256 - 1
        approval_tx = token_contract.functions.approve(router_address, max_uint).build_transaction({
            "from": sender_address,
            "chainId": 8453,
            "gas": 100000,
            "gasPrice": int(gas_price * 1.5),
            "nonce": w3.eth.get_transaction_count(sender_address),
        })
        
        signed_approval = w3.eth.account.sign_transaction(approval_tx, private_key=evm_private_key)
        approval_hash = w3.eth.send_raw_transaction(signed_approval.raw_transaction)
        print("Approval tx sent: ", approval_hash)
        # Wait for approval to be mined
        w3.eth.wait_for_transaction_receipt(approval_hash)

    # Get pair and quote
    _, fee_tier = await web3utils.get_pair_address(token_address, w3)
    quoter = w3.eth.contract(
        address=Web3.to_checksum_address("0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"),
        abi=abi.uniswap_quote,
    )
    
    quote_params = (token_address, weth_address, amount_in_wei, fee_tier, 0)
    result = quoter.functions.quoteExactInputSingle(quote_params).call()
    amount_out = result[0]
    min_out = int(amount_out * (1 - slippage / 100))
    
    # Build and send swap transaction
    router = w3.eth.contract(address=router_address, abi=abi.uniswap_router)
    swap_params = {
        "tokenIn": token_address,
        "tokenOut": weth_address,
        "fee": fee_tier,
        "recipient": sender_address,
        "deadline": int(time.time()) + 600,
        "amountIn": amount_in_wei,
        "amountOutMinimum": min_out,
        "sqrtPriceLimitX96": 0,
    }
    
    gas_price = w3.eth.gas_price
    actual_gas_price = int(gas_price * 1.5)
    
    gas_estimate = router.functions.exactInputSingle(swap_params).estimate_gas({
        "from": sender_address,
    })
    gas_limit = int(gas_estimate * 1.5)
    
    swap_tx = router.functions.exactInputSingle(swap_params).build_transaction({
        "from": sender_address,
        "chainId": 8453,
        "gas": gas_limit,
        "gasPrice": actual_gas_price,
        "nonce": w3.eth.get_transaction_count(sender_address),
    })
    
    signed_tx = w3.eth.account.sign_transaction(swap_tx, private_key=evm_private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    return tx_hash.hex()

async def _sell_confirm_sol(token_address, amount_to_sell, wallet):
    _, _, decimals, _, _ = solana_utils.get_token_info(token_address)
    sell_params = SellTokenParams(
        private_key=Wallet.decrypt_private_key(wallet["solana_private_key"]),
        token_mint=token_address,  
        token_amount=amount_to_sell,
        token_decimals=decimals
    )
    
    txid = await _sell(sell_params)

    print("Recieved txid in bot: ", txid)
    return txid

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keys_to_remove = [
        "sell_token_symbol",
        "sell_token_address",
        "sell_token_balance",
        "sell_token_price",
        "sell_amount",
        "selected_chain",
        "token_data",
        "command_type",
        "buy_token_address",
        "buy_token_symbol",
        "buy_amount",
    ]
    
    for key in keys_to_remove:
        context.user_data.pop(key, None) 
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text("Cancelled.")
    else:
        await update.message.reply_text("Cancelled.")
        
    return ConversationHandler.END

async def wallets_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        message = update.callback_query.message
        user = update.callback_query.from_user
    else:
        message = update.message
        user = update.effective_user

    user_data = db.get_user_by_telegram_id(user.id)

    if not user_data:
        await message.reply_text(
            "You are not registered. Use /start to register and create your wallets."
        )
        return

    wallet = db.get_wallet_by_user_id(user_data["id"])

    if not wallet:
        await message.reply_text("You don't have a wallet. Use /start to create one.")
        return

    evm_address = wallet.get("evm_address", "N/A")
    solana_address = wallet.get("solana_address", "N/A")

    await message.reply_text(
        f"**Your Wallet Details** 💼\n\n"
        f"**EVM Wallet**: `{evm_address}` (Tap to copy)\n"
        f"**Solana Wallet**: `{solana_address}` (Tap to copy)\n\n",
        parse_mode="Markdown",
    )


def main():
    application = Application.builder().token(BOT_TOKEN).build()

    register_chain_handlers(application)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("wallet", wallets_command))
    application.add_handler(
        CallbackQueryHandler(help_command, pattern="^help_command$")
    )
    application.add_handler(
        ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER)
    )
    application.add_handler(CallbackQueryHandler(handle_callbacks))

    register_deposit_handlers(application)
    register_withdraw_handlers(application)
    print("ApexBT Bot is now running!")
    application.run_polling()


if __name__ == "__main__":
    main()
