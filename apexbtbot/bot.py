from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from web3 import Web3
import secrets
import json
from dotenv import load_dotenv
import os

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("Telegram bot token not found. Set it in the .env file.")


# In-memory storage for demo purposes (replace with a database for production)
USER_WALLETS = {}

# Function to generate a wallet
def create_wallet():
    private_key = "0x" + secrets.token_hex(32)
    web3 = Web3()
    address = web3.eth.account.from_key(private_key).address
    return {"address": address, "private_key": private_key}

# Save wallet to "database"
def save_wallet(user_id, wallet):
    USER_WALLETS[user_id] = wallet

# Fetch wallet from "database"
def get_wallet(user_id):
    return USER_WALLETS.get(user_id)

# 1. Detect when a new user joins the group
async def new_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        user_id = member.id
        # Your wallet creation logic here
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Welcome, {member.full_name}! A new wallet has been created for you!"
        )

async def start_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Hi {update.effective_user.name}, thank you for using ApexBT Bot.")

async def check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Placeholder balance logic
    balance = "0.00 ETH"
    await update.message.reply_text(f"Your wallet balance is: {balance}")


def main():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_user_handler))
    application.add_handler(CommandHandler("start", start_bot))
    application.add_handler(CommandHandler("balance", check_balance))

    application.run_polling()

if __name__ == "__main__":
    main()