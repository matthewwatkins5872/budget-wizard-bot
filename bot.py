import os
import io
from datetime import datetime

from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# =============== Config ===============
TOKEN = os.getenv("BOT_TOKEN")

# =============== App State ===============
# STORE[user_id][period] = [ {amount, category, notes, ts}, ... ]
STORE = {}
MODE = {}                 # user_id -> "add" or None
CURRENT_PERIOD = {}       # user_id -> "YYYY-MM"

def _this_month() -> str:
    return datetime.utcnow().strftime("%Y-%m")

def _ensure_user_period(user_id: int) -> str:
    period = CURRENT_PERIOD.get(user_id)
    if not period:
        period = _this_month()
        CURRENT_PERIOD[user_id] = period
    STORE.setdefault(user_id, {}).setdefault(period, [])
    return period

def add_expense_to_store(user_id: int, amount: float, category: str, notes: str):
    period = _ensure_user_period(user_id)
    STORE[user_id][period].append({
        "amount": amount,
        "category": category,
        "notes": notes,
        "ts": datetime.utcnow()
    })

def clear_current_month(user_id: int):
    period = _ensure_user_period(user_id)
    STORE[user_id][period] = []

def get_current_month_expenses(user_id: int):
    period = _ensure_user_period(user_id)
    return STORE[user_id][period]

# =============== Parsing helpers ===============
def parse_free_expense(text: str):
    """
    Accepts a single line like:
      "1200 rent"
      "$50 groceries milk"
    Returns (amount, category, notes) or None.
    """
    parts = text.strip().split()
    if not parts:
        return None
    first = parts[0].replace("$", "").replace(",", "")
    try:
        amt = float(first)
    except ValueError:
        return None
    tokens = parts[1:]
    stopwords = {"for", "on", "to", "the", "a", "an", "my"}
    while tokens and tokens[0].lower() in stopwords:
        tokens = tokens[1:]
    cat = tokens[0] if tokens else "uncategorized"
    notes = " ".join(tokens[1:]) if len(tokens) > 1 else ""
    return amt, cat, notes

def parse_expense_block(text: str):
    """
    Accept multiple expenses separated by newlines OR slashes.
    Examples:
      1200 rent
      500 food
      200 insurance
    or:
      1200 rent / 500 food / 200 insurance
    """
    if ("\n" not in text) and ("/" in text):
        lines = [p.strip() for p in text.split("/") if p.strip()]
    else:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    items, errors = [], []
    for raw in lines:
        parsed = parse_free_expense(raw)
        if parsed:
            items.append(parsed)
        else:
            errors.append(raw)
    return items, errors

# =============== Telegram Commands ===============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    CURRENT_PERIOD[user_id] = _this_month()
    MODE[user_id] = "add"
    _ensure_user_period(user_id)
    await update.message.reply_text(
        "Welcome to Budget Wizard 🧙‍♂️\n"
        "Enter **monthly** expenses like:\n"
        "• 1200 rent\n• 60 phone\n• 230 car_insurance\n\n"
        "Paste multiple lines or use slashes: 1200 rent / 500 food / 200 insurance\n"
        "Shortcuts: **view**, **generate**, **export**, **done**.\n"
        "Type **reset** to start a new month."
    )

async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    CURRENT_PERIOD[user_id] = _this_month()
    clear_current_month(user_id)
    MODE[user_id] = "add"
    await update.message.reply_text("✅ Cleared this month's expenses. Add new items now.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def addexpense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 2:
        return await update.message.reply_text("Usage: /addexpense <amount> <category> [notes]")
    try:
        amount = float(context.args[0].replace(",", ""))
    except ValueError:
        return await update.message.reply_text("Amount must be a number.")
    category = context.args[1]
    notes = " ".join(context.args[2:]) if len(context.args) > 2 else ""
    user_id = update.effective_user.id
    add_expense_to_store(user_id, amount, category, notes)
    await update.message.reply_text(f"✅ Added ${amount:.2f} to '{category}'.")

async def addmany(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /addmany\n1200 rent\n500 groceries\n200 gas truck
    or slashes in one line.
    """
    text = update.message.text
    block = text.split("\n", 1)[1] if "\n" in text else ""
    if not block.strip():
        return await update.message.reply_text(
            "Paste multiple lines after the command, e.g.:\n"
            "/addmany\n1200 rent\n500 groceries\n200 gas\n\n"
            "You can also separate with slashes: 1200 rent / 500 food / 200 insurance"
        )
    user_id = update.effective_user.id
    items, errors = parse_expense_block(block)
    for amt, cat, notes in items:
        add_expense_to_store(user_id, amt, cat, notes)
    msg = f"✅ Added {len(items)} item(s)."
    if errors:
        msg += f"\n⚠️ Skipped {len(errors)} line(s):\n- " + "\n- ".join(errors[:5])
        if len(errors) > 5:
            msg += f"\n(and {len(errors)-5} more...)"
    await update.message.reply_text(msg)

async def viewexpenses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        items = get_current_month_expenses(user_id)
        if not items:
            return await update.message.reply_text("No expenses yet.")
        total = sum(x["amount"] for x in items)
        by_cat = {}
        for x in items:
            by_cat[x["category"]] = by_cat.get(x["category"], 0) + x["amount"]
        period = CURRENT_PERIOD[user_id]
        lines = [f"📊 {period} total: ${total:.2f}"]
        for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1]):
            lines.append(f"- {k}: ${v:.2f}")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"❌ view error: {e}")

async def generatebudget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        items = get_current_month_expenses(user_id)
        if not items:
            return await update.message.reply_text("No data yet.")
        monthly_total = sum(x["amount"] for x in items)
        by_cat = {}
        for x in items:
            by_cat[x["category"]] = by_cat.get(x["category"], 0) + x["amount"]
        period = CURRENT_PERIOD[user_id]
        lines = [f"📅 Budget ({period}):", f"Total: ${monthly_total:.2f}", ""]
        for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1]):
            lines.append(f"• {k}: ${v:.2f}")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"❌ generate error: {e}")

async def exportexcel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        from openpyxl import Workbook
        user_id = update.effective_user.id
        items = get_current_month_expenses(user_id)
        if not items:
            return await update.message.reply_text("No expenses yet.")

        wb = Workbook()
        ws = wb.active
        ws.title = "Expenses"
        ws.append(["Period", "Timestamp (UTC)", "Amount", "Category", "Notes"])
        period = CURRENT_PERIOD[user_id]
        for x in items:
            ws.append([period, x["ts"].strftime("%Y-%m-%d %H:%M:%S"),
                       float(x["amount"]), x["category"], x["notes"]])

        bio = io.BytesIO()
        wb.save(bio)
        bio.seek(0)
        await update.message.reply_document(InputFile(bio, "budget_full.xlsx"),
                                            caption="✅ Full export (free).")
    except Exception as e:
        await update.message.reply_text(f"❌ export error: {e}")

# =============== Fallback Text ===============
async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_raw = update.message.text or ""
    text = text_raw.strip().lower()
    user_id = update.effective_user.id

    # quick commands
    if text in ["reset", "new month", "start new month", "clear"]:
        clear_current_month(user_id)
        MODE[user_id] = "add"
        return await update.message.reply_text("✅ New month started. Paste expenses or type **done**.")
    if text in ["view", "summary"]:
        return await viewexpenses(update, context)
    if text in ["generate", "budget"]:
        return await generatebudget(update, context)
    if text in ["export", "excel"]:
        return await exportexcel(update, context)

    # "add ..." with block support (slashes or newlines)
    if text.startswith("add "):
        content = text_raw[4:]
        items, errors = parse_expense_block(content)
        if items:
            for amt, cat, notes in items:
                add_expense_to_store(user_id, amt, cat, notes)
            msg = f"✅ Added {len(items)} item(s)."
            if errors:
                msg += f"\n⚠️ Skipped {len(errors)} line(s):\n- " + "\n- ".join(errors[:5])
                if len(errors) > 5:
                    msg += f"\n(and {len(errors)-5} more...)"
            return await update.message.reply_text(msg)
        return await update.message.reply_text("Usage:\nadd 1200 rent / 500 food / 200 insurance")

    # Add-mode: handle multi-line and/or slashes in one go
    if MODE.get(user_id) == "add":
        block = text_raw.strip()
        items, errors = parse_expense_block(block)
        if items:
            for amt, cat, notes in items:
                add_expense_to_store(user_id, amt, cat, notes)
            msg = f"✅ Added {len(items)} item(s)."
            if errors:
                msg += f"\n⚠️ Skipped {len(errors)} line(s):\n- " + "\n- ".join(errors[:5])
                if len(errors) > 5:
                    msg += f"\n(and {len(errors)-5} more...)"
            return await update.message.reply_text(msg)

        return await update.message.reply_text(
            "Send expenses like:\n"
            "• 1200 rent\n• 500 food\n• 200 insurance\n"
            "or in one line: 1200 rent / 500 food / 200 insurance"
        )

    if text in ["done", "stop", "finish"]:
        MODE[user_id] = None
        return await update.message.reply_text("Okay. You can type **view**, **generate**, or **export** anytime.")

    return await update.message.reply_text(
        "Try: **hi** to start, `add 1200 rent`, paste multiple lines or use slashes, **view**, **generate**, **export**."
    )

# =============== Main ===============
def main():
    if not TOKEN:
        raise SystemExit("BOT_TOKEN not set.")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("addexpense", addexpense))
    app.add_handler(CommandHandler("addmany", addmany))
    app.add_handler(CommandHandler("viewexpenses", viewexpenses))
    app.add_handler(CommandHandler("generatebudget", generatebudget))
    app.add_handler(CommandHandler("exportexcel", exportexcel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
