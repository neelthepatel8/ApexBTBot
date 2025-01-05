def escape_message(balances):
    balance_message = ""
    
    for symbol, balance in balances.items():
        special_chars = ['.', '-', '$', '*', '_', '[', ']', '(', ')', '#', '+', '!']
        balance_escaped = balance
        
        for char in special_chars:
            balance_escaped = balance_escaped.replace(char, '\\' + char)
            
        balance_message += f"{symbol}: `{balance_escaped}`\n"
        
    return balance_message.rstrip()
