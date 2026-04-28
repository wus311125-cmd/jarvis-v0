from jarvis.expense import parse, store_expense

def format_reply(amount, description, direction):
    if direction == 'income':
        return f"💰 ${int(amount) if amount is not None else ''} HKD / {description} / 收入"
    else:
        return f"💸 ${int(amount) if amount is not None else ''} HKD / {description} / 支出"
