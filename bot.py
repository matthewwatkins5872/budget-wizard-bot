import os
import io
from datetime import datetime
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# ===== Config =====
TOKEN = os.getenv("BOT_TOKEN")  # Set this on Railway
PAYPAL_LINK = os.getenv("PAYPAL_LINK", "https://paypal.me/YourName/1")  # optional

# ===== Simple in-memory store (per process) =====
# STORE[user_id][period] = list of expense dicts
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
        "ts": datetime.utcnow(),
    })

def clear_current_month(user_id: int):
    period = _ensure_user_period(user_id)
    STORE[user_id][period] = []

def get_current_month_expenses(user_id: int):
    period = _ensure_user_period(user_id)
    return STORE[user_id][period]

# ---------- helper: parse free-text expense lines ----------
def parse_free_expense(text: str):
    """
    Accepts lines like:
      "12.50 groceries milk and bread"
      "$20 gas"
      "15 lunch burger"
    Returns (amount, category, notes) or None if not parseable.
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

# ================== Command handlers ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    CURRENT_PERIOD[user_id] = _this_month()
    MODE[user_id] = "add"
    _ensure_user_period(user_id)
    await update.message.reply_text(
        "Welcome to Budget Wizard 🧙‍♂️\n"
        "I’m ready to record **monthly** expenses. Send them like:\n"
        "• 1200 rent\n• 60 phone\n• 230 car_insurance\n\n"
        "Type **view** for a summary, **generate** for a budget, **export** for Excel,\n"
        "or **done** to exit add mode.\n"
        "Tip: type **reset** or **new month** to clear this month's items."
    )

async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    CURRENT_PERIOD[user_id] = _this_month()  # keep period as current month
    clear_current_month(user_id)
    MODE[user_id] = "add"
    await update.message.reply_text(
        "✅ Cleared this month's expenses. Start your **new month** now!\n"
        "Examples:\n• 1200 rent\n• 60 phone\n• 230 car_insurance"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def addexpense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Slash-command version (still supported)
    if not context.args or len(context.args) < 2:
        return await update.message.reply_text("Usage: /addexpense <amount> <category> [notes]")
    try:
        amount = float(context.args[0].replace(",", ""))
    except ValueError:
        return await update.message.reply_text("Amount must be a number. Example: /addexpense 9.99 coffee")
    category = context.args[1]
    notes = " ".join(context.args[2:]) if len(context.args) > 2 else ""
    user_id = update.effective_user.id
    add_expense_to_store(user_id, amount, category, notes)
    await update.message.reply_text(f"✅ Added ${amount:.2f} to '{category}'. Use /viewexpenses or type 'view'.")

async def viewexpenses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    items = get_current_month_expenses(user_id)
    if not items:
        return await update.message.reply_text("No expenses yet this month. Add one like: 1200 rent")
    total = sum(x["amount"] for x in items)
    by_cat = {}
    for x in items:
        by_cat[x["category"]] = by_cat.get(x["category"], 0) + x["amount"]
    period = CURRENT_PERIOD.get(user_id, _this_month())
    lines = [f"📊 {period} total: ${total:.2f}"]
    for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1]):
        lines.append(f" - {k}: ${v:.2f}")
    await update.message.reply_text("\n".join(lines))

async def generatebudget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    items = get_current_month_expenses(user_id)
    if not items:
        return await update.message.reply_text("No data yet. Add your monthly bills one by one.")

    monthly_total = sum(x["amount"] for x in items)

    # per-category monthly totals
    by_cat = {}
    for x in items:
        by_cat[x["category"]] = by_cat.get(x["category"], 0) + x["amount"]

    period = CURRENT_PERIOD.get(user_id, _this_month())
    lines = [
        f"📅 Monthly budget snapshot ({period}):",
        f"- Monthly total: ${monthly_total:.2f}",
        "",
        "By category:"
    ]
    for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1]):
        lines.append(f"• {k}: ${v:.2f}")

    lines.append("\nType **export** to download Excel, or **reset** to start a new month.")
    await update.message.reply_text("\n".join(lines))

async def exportexcel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        from openpyxl import Workbook
    except Exception as e:
        return await update.message.reply_text(f"openpyxl missing: {e}")
    user_id = update.effective_user.id
    items = get_current_month_expenses(user_id)
    if not items:
        return await update.message.reply_text("No expenses yet to export.")
    wb = Workbook()
    ws = wb.active
    ws.title = "Expenses"
    ws.append(["Period", "Timestamp (UTC)", "Amount", "Category", "Notes"])
    period = CURRENT_PERIOD.get(user_id, _this_month())
    for x in items:
        ws.append([period, x["ts"].strftime("%Y-%m-%d %H:%M:%S"), float(x["amount"]), x["category"], x["notes"]])
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    await update.message.reply_document(InputFile(bio, "budget_wizard_expenses.xlsx"),
                                        caption="Here is your Excel export.")

async def unlockfull(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Unlock the full detailed report for $1:\n"
        f"{PAYPAL_LINK}\n\n"
        "After payment, reply 'paid' and I'll unlock your report (demo)."
    )

# ================== Conversational fallback ==================

async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id

    # normalize
    low = text.lower()

    # Start a fresh month (no slash)
    if low in ["reset", "clear", "new month", "start new month"]:
        CURRENT_PERIOD[user_id] = _this_month()
        clear_current_month(user_id)
        MODE[user_id] = "add"
        return await update.message.reply_text(
            "✅ New month started. Add expenses like `1200 rent`, `60 phone`.\n"
            "Type **view** or **generate** anytime."
        )

    # Enter add mode with greetings
    if low in ["hi", "hello", "hey", "start", "go"]:
        CURRENT_PERIOD[user_id] = _this_month()
        MODE[user_id] = "add"
        _ensure_user_period(user_id)
        return await update.message.reply_text(
            "Great! Send expenses like: 1200 rent\n"
            "Say **done** when finished.\n"
            "Shortcuts: **view**, **generate**, **export**, **unlock**."
        )

    # Exit add mode
    if low in ["done", "stop", "finish"]:
        MODE[user_id] = None
        return await update.message.reply_text(
            "Okay. You can type **view**, **generate**, or **export** anytime."
        )

    # Keyword shortcuts (no slash)
    if low in ["view", "summary"]:
        return await viewexpenses(update, context)
    if low in ["generate", "budget"]:
        return await generatebudget(update, context)
    if low in ["export", "excel"]:
        return await exportexcel(update, context)
    if low in ["unlock", "buy", "pay"]:
        return await unlockfull(update, context)
    if low == "paid":
        return await update.message.reply_text("✅ Payment noted. Your full report is unlocked!")

    # Add via "add ..." command
    if low.startswith("add "):
        parsed = parse_free_expense(text[4:])
        if not parsed:
            return await update.message.reply_text("Usage: add <amount> <category> [notes]")
        amt, cat, notes = parsed
        add_expense_to_store(user_id, amt, cat, notes)
        return await update.message.reply_text(f"✅ Added ${amt:.2f} to '{cat}'. Next expense?")

    # Add-mode: bare expense lines (e.g., "1200 rent", "60 phone")
    if MODE.get(user_id) == "add":
        parsed = parse_free_expense(text)
        if parsed:
            amt, cat, notes = parsed
            add_expense_to_store(user_id, amt, cat, notes)
            return await update.message.reply_text("✅ Added. Next expense or type **done**.")
        return await update.message.reply_text(
            "Send an expense like `1200 rent` or type **done**.\n"
            "Shortcuts: **view**, **generate**, **export**."
        )

    # Fallback help
    return await update.message.reply_text(
        "Try: **hi** to start adding, `add 1200 rent`, **view**, **generate**, **export**, or **unlock**."
    )

# ================== App bootstrap ==================

def main():
    if not TOKEN:
        raise SystemExit("BOT_TOKEN is not set.")
    app = Application.builder().token(TOKEN).build()

    # Slash commands (still supported)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))          # <-- added
    app.add_handler(CommandHandler("addexpense", addexpense))
    app.add_handler(CommandHandler("viewexpenses", viewexpenses))
    app.add_handler(CommandHandler("generatebudget", generatebudget))
    app.add_handler(CommandHandler("exportexcel", exportexcel))
    app.add_handler(CommandHandler("unlockfull", unlockfull))

    # Natural text handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
