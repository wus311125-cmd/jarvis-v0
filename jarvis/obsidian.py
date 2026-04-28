def render_daily(expenses_rows):
    """expenses_rows: list of dicts with keys amount, description, direction"""
    expenses = [r for r in expenses_rows if r.get('direction','expense')=='expense']
    incomes = [r for r in expenses_rows if r.get('direction')=='income']

    out = []
    out.append('# Daily Note')
    out.append('\n')
    out.append('💸 Expenses')
    for e in expenses:
        out.append(f"- ${int(e.get('amount',0))} / {e.get('description','')} ")

    out.append('\n')
    out.append('💰 Income')
    for i in incomes:
        out.append(f"- ${int(i.get('amount',0))} / {i.get('description','')} ")

    return '\n'.join(out)
