import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import sql
import os
from dotenv import load_dotenv

from apexbtbot.queries import tables

load_dotenv()


class Database:
    def __init__(self):
        self.DATABASE_URL = os.getenv("DATABASE_URL")
        self._connection = None

    def connect(self):
        if not self._connection:
            self._connection = psycopg2.connect(
                self.DATABASE_URL, cursor_factory=RealDictCursor
            )
        return self._connection

    def close(self):
        if self._connection:
            self._connection.close()
            self._connection = None

    def execute(self, query, params=None, fetch_one=False, fetch_all=False):
        conn = self.connect()
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)
            if fetch_one:
                result = cursor.fetchone()
            elif fetch_all:
                result = cursor.fetchall()
            else:
                result = None
            conn.commit()
            return result
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()

    def init(self):
        # self.rm_all()
        for query in tables:
            self.execute(query)
        
    def rm_all(self):
        tables = ["transactions", "wallets", "users"]
        conn = self.connect()
        cursor = conn.cursor()
        for table in tables:
            query = f"DELETE FROM {table};"
            cursor.execute(query)
        conn.commit()
        
    def add_user(self, telegram_id, name):
        query = """
        INSERT INTO users (telegram_id, name)
        VALUES (%s, %s)
        ON CONFLICT (telegram_id) DO NOTHING
        RETURNING id;
        """
        return self.execute(query, (telegram_id, name), fetch_one=True)

    def get_user_by_telegram_id(self, telegram_id):
        query = "SELECT * FROM users WHERE telegram_id = %s;"
        return self.execute(query, (telegram_id,), fetch_one=True)

    def add_wallet(self, user_id, evm_address, evm_private_key, solana_address, solana_private_key):
        query = """
        INSERT INTO wallets (user_id, evm_address, evm_private_key, solana_address, solana_private_key)
        VALUES (%s, %s, %s, %s, %s);
        """
        self.execute(query, (user_id, evm_address, evm_private_key, solana_address, solana_private_key))

    def get_wallet_by_user_id(self, user_id):
        query = "SELECT * FROM wallets WHERE user_id = %s;"
        return self.execute(query, (user_id,), fetch_one=True)

    def log_transaction(self, user_id, transaction_type, chain, token, amount):
        query = """
        INSERT INTO transactions (user_id, transaction_type, chain, token, amount)
        VALUES (%s, %s, %s, %s, %s);
        """
        self.execute(query, (user_id, transaction_type, chain, token, amount))

    def get_transactions_by_user_id(self, user_id):
        query = "SELECT * FROM transactions WHERE user_id = %s ORDER BY created_at DESC;"
        return self.execute(query, (user_id,), fetch_all=True)

    def get_all_active_users(self):
        query = """
        SELECT users.* 
        FROM users 
        INNER JOIN wallets ON users.id = wallets.user_id 
        WHERE wallets.evm_address IS NOT NULL;
        """
        return self.execute(query, fetch_all=True)
    
    def get_wallet_address_by_user_id(self, user_id):
        query = """
        SELECT evm_address 
        FROM wallets 
        WHERE user_id = %s;
        """
        return self.execute(query, (user_id,), fetch_one=True)["evm_address"]