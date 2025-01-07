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
from decimal import Decimal
from datetime import datetime
from io import BytesIO
import os
import time
import qrcode


from apexbtbot.database import Database
from apexbtbot.wallet import Wallet
from apexbtbot import abi, web3utils, settings, util
from apexbtbot.alchemy import AlchemyAPIWrapper

db = Database()
db.init()

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ETH_NODE_URL = os.getenv("ETH_NODE_URL")

BUY_TOKEN_ADDRESS, BUY_AMOUNT_CHOICE, BUY_AMOUNT, BUY_CONFIRM = range(4)
SELL_TOKEN_ADDRESS, SELL_DESTINATION_TOKEN, SELL_AMOUNT, SELL_CONFIRM = range(4)

SHOWING_ADDRESS = 1

CHAIN_SELECTION = range(100, 101)

SELL_AMOUNT_CHOICE = "SELL_AMOUNT_CHOICE"

alchemy = AlchemyAPIWrapper(ETH_NODE_URL)

w3 = Web3(Web3.HTTPProvider(ETH_NODE_URL))

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

def _get_dynamic_context(update: Update):
    if update.callback_query:
        return update.callback_query.from_user, update.callback_query.message

    return update.effective_user, update.message

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
                CallbackQueryHandler(sell_token_selected, pattern="^sell_[0-9]+$"),
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

async def start_sell_chain_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["command_type"] = "sell"
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
            wallet_address = db.get_wallet_address_by_user_id(db_user["id"], chain="solana")
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

    if selected_chain == "base_chain":
        await query.message.edit_text("Enter the token address you want to buy:")
        return BUY_TOKEN_ADDRESS
    else:
        # SOLANA BUY
        await query.message.edit_text("Solana buying coming soon!")
        return ConversationHandler.END

async def handle_chain_sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    selected_chain = query.data
    context.user_data["selected_chain"] = selected_chain

    if selected_chain == "base_chain":
        return await start_sell_conversation(update, context)
    else:
        # SOLANA SELL
        await query.message.edit_text("Solana selling coming soon!")
        return ConversationHandler.END

def register_deposit_handlers(application):
    deposit_handler = CommandHandler("deposit", deposit_start)
    qr_handler = CallbackQueryHandler(show_qr_code, pattern="^show_qr$")
    check_balance_handler = CallbackQueryHandler(
        check_deposit_balance, pattern="^check_balance$"
    )

    application.add_handler(deposit_handler)
    application.add_handler(qr_handler)
    application.add_handler(check_balance_handler)

async def deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        user_data = db.get_user_by_telegram_id(user.id)
        wallet = db.get_wallet_by_user_id(user_data["id"])

        keyboard = [
            [
                InlineKeyboardButton("Show QR Code", callback_data="show_qr"),
                InlineKeyboardButton("Check Balance", callback_data="check_balance"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        message = (
            "📥 *Deposit Funds*\n\n"
            "To deposit funds, send ETH or tokens to your wallet address:\n"
            f"`{wallet['evm_address']}`\n\n"
            "*Supported Networks:*\n"
            "• Base Network (Chain ID: 8453)\n\n"
            "*Supported Tokens:*\n"
            "• ETH (Native token)\n"
            "• USDC (0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913)\n"
            "• Other ERC20 tokens\n\n"
            "⚠️ *Important:*\n"
            "• Only send tokens on the Base network\n"
            "• Minimum deposit: 0.01 ETH or equivalent\n"
            "• Deposits usually confirm within 1-2 minutes\n\n"
            "Click 'Check Balance' after sending to verify your deposit."
        )

        await update.callback_query.message.reply_text(
            message, parse_mode="Markdown", reply_markup=reply_markup
        )

        return SHOWING_ADDRESS

    except Exception as e:
        print(f"Error in deposit_start: {e}")
        await update.callback_query.message.reply_text(
            "Sorry, there was an error processing your deposit request. Please try again later."
        )
        return ConversationHandler.END

async def show_qr_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()

        user = query.from_user
        user_data = db.get_user_by_telegram_id(user.id)
        wallet = db.get_wallet_by_user_id(user_data["id"])

        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(wallet["evm_address"])
        qr.make(fit=True)

        img_buffer = BytesIO()
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(img_buffer, format="PNG")
        img_buffer.seek(0)

        caption = (
            "Scan this QR code to get your deposit address\n"
            f"Address: `{wallet['evm_address']}`"
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

    wallet = db.get_wallet_by_user_id(user_data["id"])

    if wallet:
        try:
            balance_string = Wallet.build_evm_balance_string(wallet["evm_address"])
            await update.message.reply_text(
                f"<b>Welcome back to ApexBT Bot, {user.full_name}!</b>\n\n"
                f"<u>Your Wallet Details:</u>\n"
                f"🔑 <b>EVM Wallet:</b> <code>{wallet['evm_address']}</code> (Tap to copy)\n"
                f"\n\n{balance_string}\n\n"
                f"🔑 <b>Solana Wallet:</b> <code>{wallet['solana_address']}</code> (Tap to copy)",
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

            db.add_wallet(
                user_data["id"],
                evm_wallet["address"],
                evm_wallet["private_key"],
                solana_wallet["address"],
                solana_wallet["private_key"],
            )

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
                "I cannot send you private messages, please initiate a conversation with me.",
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
        return await deposit_start(update, context)

    elif query.data == "withdraw":
        return await withdraw_start(update, context)

    elif query.data == "show_qr":
        return await show_qr_code(update, context)

    elif query.data in ["base_chain", "solana_chain"]:
        command_type = context.user_data.get("command_type")
        
        if command_type == "balance":
            return await handle_chain_balance(update, context)

    elif query.data == "help":
        await help_command(update, context)
        return ConversationHandler.END

async def get_user_token_balance(
    token_address: str, user_id: int, w3: Web3
) -> tuple[float, int]:
    try:
        user_data = db.get_user_by_telegram_id(user_id)
        wallet = db.get_wallet_by_user_id(user_data["id"])
        if not wallet:
            return None, None

        evm_address = wallet["evm_address"]

        token_contract = w3.eth.contract(
            address=w3.to_checksum_address(token_address), abi=abi.erc20
        )

        decimals = token_contract.functions.decimals().call()
        balance_wei = token_contract.functions.balanceOf(evm_address).call()
        balance_decimal = balance_wei / (10**decimals)

        return balance_decimal, decimals

    except Exception as e:
        print(f"Error fetching token balance: {e}")
        return None, None


async def prompt_for_token(update: Update, operation: str):
    message = f"Enter a token address to {operation}"
    if update.callback_query:
        await update.callback_query.message.reply_text(message)
    else:
        await update.message.reply_text(message)
    return BUY_TOKEN_ADDRESS if operation == "buy" else SELL_TOKEN_ADDRESS

async def start_buy_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await prompt_for_token(update, "buy")

async def token_not_found(update: Update, operation: str):
    keyboard = [
        [
            InlineKeyboardButton(
                "Retry", callback_data=f"retry_{operation}_token_address"
            )
        ]
    ]
    await update.message.reply_text(
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

async def validate_token(token_address, update: Update, operation: str):
    if not Web3.is_address(token_address):
        await token_not_found(update, operation)
        return False
    return True

async def buy_token_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token_address = update.message.text.strip()
    if not await validate_token(token_address, update, "buy"):
        return BUY_TOKEN_ADDRESS

    name, symbol, decimals, price_in_eth = await web3utils.get_token_info(
        token_address, w3
    )

    # Check liquidity and get pool info
    try:
        _, fee_tier = await web3utils.get_pair_address(token_address, w3)

        # Try to quote a small test amount (0.1 ETH) to check liquidity
        quoter = w3.eth.contract(
            address=Web3.to_checksum_address(
                "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"
            ),
            abi=abi.uniswap_quote,
        )

        test_amount = Web3.to_wei(0.1, "ether")
        quote_params = (
            Web3.to_checksum_address(
                "0x4200000000000000000000000000000000000006"
            ),  # WETH
            Web3.to_checksum_address(token_address),
            test_amount,
            fee_tier,
            0,
        )

        result = quoter.functions.quoteExactInputSingle(quote_params).call()
        liquidity_warning = ""

        try:
            test_quote = quoter.functions.quoteExactInputSingle(
                (
                    Web3.to_checksum_address(
                        "0x4200000000000000000000000000000000000006"
                    ),
                    Web3.to_checksum_address(token_address),
                    Web3.to_wei(1, "ether"),
                    fee_tier,
                    0,
                )
            ).call()

            if (
                not test_quote
                or abs(
                    test_quote[0] / Web3.to_wei(1, "ether") - result[0] / test_amount
                )
                > 0.05
            ):
                liquidity_warning = (
                    "\n⚠️ *Warning: Low liquidity detected. Trade carefully!*"
                )
        except Exception:
            liquidity_warning = (
                "\n⚠️ *Warning: Very low liquidity. Large trades may fail!*"
            )

    except Exception as e:
        if "SPL" in str(e):
            await update.message.reply_text(
                f"⚠️ This token has extremely low liquidity and may be difficult to trade.\n"
                f"Consider checking the pool on Basescan first:\n"
                f"[View Pool ↗](https://basescan.org/token/{token_address})",
                parse_mode="Markdown",
            )
            return BUY_TOKEN_ADDRESS
        liquidity_warning = (
            "\n⚠️ *Warning: Could not verify liquidity. Trade with caution!*"
        )

    context.user_data["buy_token_address"] = token_address
    context.user_data["buy_token_symbol"] = symbol
    context.user_data["buy_token_decimals"] = decimals

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

    price_in_usd = (
        Decimal(price_in_eth) * Decimal(eth_to_usd) if price_in_eth else "N/A"
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "Enter amount (in ETH)", callback_data="buy_amount_eth"
            ),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Buy ${symbol} -- ({name})\n"
        f"`{token_address}`\n"
        f"[Basescan ↗](https://basescan.org/token/{token_address})"
        f"\n\nYour balance: {eth_balance:.4f} ETH\n"
        f"Price: ${price_in_usd:.8f} per token ({price_in_eth:.9f} ETH)"
        f"{liquidity_warning}\n\n",
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )

    return BUY_AMOUNT_CHOICE

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
            "Enter the amount in USD you want to buy", parse_mode="Markdown"
        )

    return BUY_AMOUNT

async def buy_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
        if amount <= 0:
            raise ValueError("Amount must be positive.")
    except ValueError:
        await update.message.reply_text("Invalid amount.")
        return ConversationHandler.END

    token_address = context.user_data["buy_token_address"]
    token_symbol = context.user_data["buy_token_symbol"]
    amount_type = context.user_data["buy_amount_type"]

    try:
        user = update.effective_user
        user_data = db.get_user_by_telegram_id(user.id)
        wallet = db.get_wallet_by_user_id(user_data["id"])
        if not wallet:
            await no_wallet(update, context)
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
        estimated_gas_cost = Web3.to_wei(gas_fee, "gwei") * 21000
        total_cost = Web3.to_wei(eth_amount, "ether") + estimated_gas_cost

        if Web3.from_wei(total_cost, "ether") > eth_balance:
            await update.message.reply_text(
                f"Insufficient balance in your EVM wallet. Please deposit and try again.\n"
                f"Required: {Web3.from_wei(total_cost, 'ether'):.6f} ETH "
                f"(including gas)\n"
                f"Your balance: {eth_balance:.6f} ETH"
            )
            return ConversationHandler.END

        context.user_data.update(
            {"buy_amount_eth": eth_amount, "buy_amount_tokens": token_amount}
        )

        slippage = settings.default.slippage
        keyboard = [
            [
                InlineKeyboardButton("Confirm", callback_data="buy_confirm"),
                InlineKeyboardButton("Cancel", callback_data="cancel"),
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

    token_address = context.user_data["buy_token_address"]
    token_symbol = context.user_data["buy_token_symbol"]
    token_decimals = context.user_data["buy_token_decimals"]
    amount_in_eth = context.user_data["buy_amount_eth"]
    slippage = settings.default.gas_fee
    user = update.effective_user
    user_data = db.get_user_by_telegram_id(user.id)
    wallet = db.get_wallet_by_user_id(user_data["id"])
    evm_private_key = Wallet.decrypt_private_key(wallet["evm_private_key"])
    sender_address = wallet["evm_address"]

    keyboard_balance = [
        [
            InlineKeyboardButton(
                text="View your Positions", callback_data="check_balance"
            )
        ]
    ]

    try:
        current_gas_price = w3.eth.gas_price
        gas_price = int(current_gas_price * 1.2)

        weth_address = "0x4200000000000000000000000000000000000006"

        pool_address, fee_tier = await web3utils.get_pair_address(token_address, w3)

        amount_in_wei = Web3.to_wei(amount_in_eth, "ether")

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

        await query.message.reply_text(
            f"Buy transaction sent successfully!\n"
            f"Amount In: {amount_in_eth} ETH\n"
            f"Minimum Tokens Out: {(min_tokens_out / (10 ** token_decimals)):.6f} {token_symbol}\n"
            f"Transaction Hash: `{tx_hash.hex()}`\n"
            f"[View it on Basescan ↗](https://basescan.org/tx/0x{tx_hash.hex()})",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard_balance),
        )

    except exceptions.Web3RPCError as e:
        if "replacement transaction underpriced" in str(e):
            try:
                gas_price = int(current_gas_price * 1.5)
                transaction["gasPrice"] = gas_price
                signed_tx = w3.eth.account.sign_transaction(
                    transaction, private_key=evm_private_key
                )
                tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                await query.message.reply_text(
                    f"Buy transaction sent successfully (with higher gas)!\n"
                    f"Transaction Hash: `{tx_hash.hex()}`\n"
                    f"[View it on Basescan ↗](https://basescan.org/tx/0x{tx_hash.hex()})",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard_balance),
                )
            except Exception as retry_e:
                await query.message.reply_text(
                    f"Failed to send transaction even with higher gas: {str(retry_e)}"
                )
        else:
            await query.message.reply_text(f"An error occurred: {str(e)}")
    except Exception as e:
        print(f"Error during buy transaction: {e}")
        await query.message.reply_text(f"An error occurred: {str(e)}")

    return ConversationHandler.END

async def start_sell_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        message = update.callback_query.message
        user = update.callback_query.from_user
    else:
        message = update.message
        user = update.effective_user

    try:
        loading_message = await message.reply_text(
            "Fetching your token balances, please wait... ⏳", parse_mode="HTML"
        )

        user_data = db.get_user_by_telegram_id(user.id)
        wallet_address = db.get_wallet_address_by_user_id(user_data["id"])
        token_balances = Wallet.get_erc20_balances(wallet_address)

        context.user_data["token_data"] = {}
        message_parts = ["Select a token to sell:\n"]
        keyboard = []

        for token_address, data in token_balances.items():
            balance = data["balance"]
            symbol = data["symbol"]
            price_in_usd = data["price_in_usd"]
            value_in_usd = data["value_in_usd"]
            name = data["name"]

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

        balance_string = Wallet.build_evm_balance_string(
            wallet_address, no_title=True, no_eth=True
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

    message = (
        f"Sell ${symbol} - {token_name}\n\n"
        f"`{address}`\n"
        f"[Basescan ↗](https://basescan.org/token/{address})\n"
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
            f"Enter the amount you want to sell (max {balance:.4f}):"
        )
        return SELL_AMOUNT

    percentage = int(amount_type)
    sell_amount = (percentage / 100) * balance
    context.user_data["sell_amount"] = sell_amount

    return await show_sell_confirmation(update, context)

async def show_sell_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    symbol = context.user_data["sell_token_symbol"]
    amount = context.user_data["sell_amount"]
    price_in_usd = context.user_data["sell_token_price"]
    name = context.user_data["sell_token_name"]

    value_usd = price_in_usd * amount

    eth_price_usd = alchemy.get_eth_price()

    price_in_eth = value_usd / eth_price_usd
    message = (
        f"*Confirm Sell Order*\n\n"
        f"Token: ${symbol} - ({name})\n"
        f"Amount: {amount:.4f}\n"
        f"Value: ${value_usd:.4f}\n"
        f"Price per token: ${price_in_usd:.4f}\n\n"
        f"You will receive {price_in_eth:.6f} ETH\n"
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

    try:
        user = query.from_user
        user_data = db.get_user_by_telegram_id(user.id)
        wallet = db.get_wallet_by_user_id(user_data["id"])
        if not wallet:
            await no_wallet(update, context)
            return ConversationHandler.END

        token_address = Web3.to_checksum_address(
            context.user_data["sell_token_address"]
        )
        amount_to_sell = context.user_data["sell_amount"]
        slippage = settings.default.slippage
        sender_address = wallet["evm_address"]
        evm_private_key = Wallet.decrypt_private_key(wallet["evm_private_key"])

        router_address = Web3.to_checksum_address(
            "0x2626664c2603336E57B271c5C0b26F421741e481"
        )
        weth_address = Web3.to_checksum_address(
            "0x4200000000000000000000000000000000000006"
        )

        token_contract = w3.eth.contract(address=token_address, abi=abi.erc20)

        decimals = token_contract.functions.decimals().call()
        amount_in_wei = int(amount_to_sell * (10**decimals))

        status_message = await query.message.reply_text("Checking token approval...")

        current_allowance = token_contract.functions.allowance(
            sender_address, router_address
        ).call()

        if current_allowance < amount_in_wei:
            await status_message.edit_text("Approving token spend...")

            gas_price = w3.eth.gas_price
            max_uint = 2**256 - 1

            approval_tx = token_contract.functions.approve(
                router_address, max_uint
            ).build_transaction(
                {
                    "from": sender_address,
                    "chainId": 8453,
                    "gas": 100000,
                    "gasPrice": int(gas_price * 1.5),
                    "nonce": w3.eth.get_transaction_count(sender_address),
                }
            )

            signed_approval = w3.eth.account.sign_transaction(
                approval_tx, private_key=evm_private_key
            )
            approval_hash = w3.eth.send_raw_transaction(signed_approval.raw_transaction)

            await status_message.edit_text(
                f"Approval transaction sent!\n"
                f"[View on Basescan ↗](https://basescan.org/tx/{approval_hash.hex()})",
                parse_mode="Markdown",
            )

            try:
                receipt = w3.eth.wait_for_transaction_receipt(approval_hash, timeout=60)
                if receipt.status != 1:
                    await status_message.edit_text(
                        "❌ Approval failed. Please try again."
                    )
                    return ConversationHandler.END
            except Exception as e:
                await status_message.edit_text(
                    "Approval taking longer than expected. Please verify on Basescan and try again.\n"
                    f"[View on Basescan ↗](https://basescan.org/tx/{approval_hash.hex()})",
                    parse_mode="Markdown",
                )
                return ConversationHandler.END

        await status_message.edit_text("Verifying balances...")

        token_balance = token_contract.functions.balanceOf(sender_address).call()
        eth_balance = w3.eth.get_balance(sender_address)
        new_allowance = token_contract.functions.allowance(
            sender_address, router_address
        ).call()

        if amount_in_wei > token_balance and (amount_in_wei - token_balance) < 1000:
            amount_in_wei = token_balance
            amount_to_sell = amount_in_wei / (10**decimals)
            print(f"Adjusted to maximum available balance: {amount_in_wei}")
        elif token_balance < amount_in_wei:
            await status_message.edit_text(
                "❌ Insufficient token balance for the trade."
            )
            return ConversationHandler.END

        await status_message.edit_text("Getting price quote...")

        _, fee_tier = await web3utils.get_pair_address(token_address, w3)

        quoter = w3.eth.contract(
            address=Web3.to_checksum_address(
                "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"
            ),
            abi=abi.uniswap_quote,
        )

        quote_params = (token_address, weth_address, amount_in_wei, fee_tier, 0)

        try:
            print(f"Getting quote with params: {quote_params}")
            result = quoter.functions.quoteExactInputSingle(quote_params).call()
            print(f"Quote result: {result}")
            amount_out = result[0]
            min_out = int(amount_out * (1 - slippage / 100))
        except Exception as e:
            print(f"Quote error: {e}")
            await status_message.edit_text(
                "Failed to get price quote. This could mean insufficient liquidity."
            )
            return ConversationHandler.END

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

        try:
            print(f"Estimating gas with params: {swap_params}")
            gas_estimate = router.functions.exactInputSingle(swap_params).estimate_gas(
                {
                    "from": sender_address,
                }
            )
            print(f"Gas estimate: {gas_estimate}")
        except Exception as e:
            print(f"Gas estimation error: {e}")
            await status_message.edit_text(
                "Failed to estimate gas. This could mean the trade is not possible."
            )
            return ConversationHandler.END
        gas_limit = int(gas_estimate * 1.5)

        gas_price = w3.eth.gas_price

        gas_price = w3.eth.gas_price
        actual_gas_price = int(gas_price * 1.5)
        estimated_gas_cost_wei = actual_gas_price * gas_limit
        estimated_gas_cost_eth = w3.from_wei(estimated_gas_cost_wei, "ether")

        min_out_eth = w3.from_wei(min_out, "ether")
        amount_out_eth = w3.from_wei(amount_out, "ether")

        swap_tx = router.functions.exactInputSingle(swap_params).build_transaction(
            {
                "from": sender_address,
                "chainId": 8453,
                "gas": gas_limit,
                "gasPrice": actual_gas_price,
                "nonce": w3.eth.get_transaction_count(sender_address),
            }
        )

        confirm_message = (
            "🔄 *Transaction Details*\n\n"
            f"*Selling:* {amount_to_sell:.4f} {context.user_data['sell_token_symbol']}\n"
            f"*Expected ETH:* {amount_out_eth:.4f} ETH\n"
            f"*Minimum ETH:* {min_out_eth:.4f} ETH\n"
            f"*Slippage:* {slippage}%\n\n"
            "*Gas Details:*\n"
            f"• Gas Price: {w3.from_wei(actual_gas_price, 'gwei'):.2f} Gwei\n"
            f"• Gas Limit: {gas_limit:,}\n"
            f"• Est. Gas Cost: {estimated_gas_cost_eth:.6f} ETH\n\n"
            "*Ready to send transaction. Please wait...*"
        )

        await status_message.edit_text(confirm_message, parse_mode="Markdown")

        signed_tx = w3.eth.account.sign_transaction(
            swap_tx, private_key=evm_private_key
        )
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)

        keyboard_balance = [
            [InlineKeyboardButton(text="Check Balance", callback_data="check_balance")]
        ]

        success_message = (
            "✅ *Sell Transaction Sent!*\n\n"
            f"*Amount:* {amount_to_sell:.4f} {context.user_data['sell_token_symbol']}\n"
            f"*Expected ETH:* {amount_out_eth:.4f}\n"
            f"*Gas Price:* {w3.from_wei(actual_gas_price, 'gwei'):.2f} Gwei\n"
            f"*Transaction Hash:* `{tx_hash.hex()}`\n\n"
            f"[View on Basescan ↗](https://basescan.org/tx/0x{tx_hash.hex()})"
        )

        await status_message.edit_text(
            success_message,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard_balance),
        )

    except Exception as e:
        error_message = str(e)
        if "STF" in error_message:
            await query.message.reply_text(
                "Safe Transfer Failed. This could be due to:\n"
                "1. Insufficient token balance\n"
                "2. Token transfer restrictions\n"
                "3. Insufficient ETH for gas\n"
                "Please check your balances and try again."
            )
        else:
            await query.message.reply_text(f"An error occurred: {error_message}")
            print(f"Detailed error in sell_confirm: {e}")

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if update.callback_query:
        message = update.callback_query.message
    await message.reply_text("Cancelled.")
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
    application.add_handler(CommandHandler("deposit", deposit_start))
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
