import os
import io
from datetime import datetime
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# ===== Config =====
TOKEN = os.getenv("BOT_TOKEN")  # Set this on Railway
PAYPAL_LINK = os.getenv("PAYPAL_LINK", "https://paypal.me/YourName/1")  # optional

# ===== Simple in-memory store (per process) =====
# For production, replace with a database (SQLite, Postgres, etc.).
STORE = {}  # user_id -> list of {"amount": float, "category": str, "notes": str, "ts": datetime}
MODE = {}   # user_id -> "add" or None

def add_expense_to_store(user_id: int, amount: float, category: str, notes: str):
    STORE.setdefault(user_id, []).append({
        "amount": amount,
        "category": category,
        "notes": notes,
        "ts": datetime.utcnow()
    })

def get_expenses(user_id: int):
    return STORE.get(user_id, [])

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
    cat = parts[1] if len(parts) > 1 else "uncategorized"
    notes = " ".join(parts[2:]) if len(parts) > 2 else ""
    return amt, cat, notes

# ================== Command handlers ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    MODE[user_id] = "add"
    await update.message.reply_text(
        "Welcome to Budget Wizard 🧙‍♂️\n"
        "I’m ready to record expenses. Send them like:\n"
        "• 12.50 groceries milk and bread\n"
        "• 20 gas\n\n"
        "Type **view** for a summary, **generate** for a budget, **export** for Excel,\n"
        "or **done** to exit add mode."
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
    items = get_expenses(user_id)
    if not items:
        return await update.message.reply_text("No expenses yet. Add one like: 12.50 groceries milk and bread")
    total = sum(x["amount"] for x in items)
    by_cat = {}
    for x in items:
        by_cat[x["category"]] = by_cat.get(x["category"], 0) + x["amount"]
    lines = [f"📊 Total: ${total:.2f}"]
    for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1]):
        lines.append(f" - {k}: ${v:.2f}")
    await update.message.reply_text("\n".join(lines))

async def generatebudget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    items = get_expenses(user_id)
    if not items:
        return await update.message.reply_text("No data yet. Add expenses first.")
    total = sum(x["amount"] for x in items)
    days = max((datetime.utcnow() - min(x["ts"] for x in items)).days + 1, 1)
    avg_daily = total / days
    rec_daily = avg_daily * 0.7
    await update.message.reply_text(
        f"🧮 Budget snapshot:\n"
        f"- Avg daily spend: ${avg_daily:.2f}\n"
        f"- Suggested cap: ${rec_daily:.2f}/day\n"
        f"Type **export** to download Excel."
    )

async def exportexcel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        from openpyxl import Workbook
    except Exception as e:
        return await update.message.reply_text(f"openpyxl missing: {e}")
    user_id = update.effective_user.id
    items = get_expenses(user_id)
    if not items:
        return await update.message.reply_text("No expenses yet to export.")
    wb = Workbook()
    ws = wb.active
    ws.title = "Expenses"
    ws.append(["Timestamp (UTC)", "Amount", "Category", "Notes"])
    for x in items:
        ws.append([x["ts"].strftime("%Y-%m-%d %H:%M:%S"), float(x["amount"]), x["category"], x["notes"]])
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
    text = update.message.text.strip().lower()
    user_id = update.effective_user.id

    # Enter add mode with greetings
    if text in ["hi", "hello", "hey", "start", "go"]:
        MODE[user_id] = "add"
        return await update.message.reply_text(
            "Great! Send expenses like: 12.50 groceries notes\n"
            "Say **done** when finished.\n"
            "Shortcuts: **view**, **generate**, **export**, **unlock**."
        )

    # Exit add mode
    if text in ["done", "stop", "finish"]:
        MODE[user_id] = None
        return await update.message.reply_text(
            "Okay. You can type **view**, **generate**, or **export** anytime."
        )

    # Keyword shortcuts (no slash)
    if text in ["view", "summary"]:
        return await viewexpenses(update, context)
    if text in ["generate", "budget"]:
        return await generatebudget(update, context)
    if text in ["export", "excel"]:
        return await exportexcel(update, context)
    if text in ["unlock", "buy", "pay"]:
        return await unlockfull(update, context)
    if text == "paid":
        return await update.message.reply_text("✅ Payment noted. Your full report is unlocked!")

    # Add via "add ..." command
    if text.startswith("add "):
        parsed = parse_free_expense(text[4:])
        if not parsed:
            return await update.message.reply_text("Usage: add <amount> <category> [notes]")
        amt, cat, notes = parsed
        add_expense_to_store(user_id, amt, cat, notes)
        return await update.message.reply_text(f"✅ Added ${amt:.2f} to '{cat}'. Next expense?")

    # Add-mode: bare expense lines (e.g., "12 pizza", "20 gas")
    if MODE.get(user_id) == "add":
        parsed = parse_free_expense(update.message.text)
        if parsed:
            amt, cat, notes = parsed
            add_expense_to_store(user_id, amt, cat, notes)
            return await update.message.reply_text("✅ Added. Next expense or type **done**.")
        return await update.message.reply_text(
            "Send an expense like `12.50 groceries lunch` or type **done**.\n"
            "Shortcuts: **view**, **generate**, **export**."
        )

    # Fallback help
    return await update.message.reply_text(
        "Try: **hi** to start adding, `add 12 coffee`, **view**, **generate**, **export**, or **unlock**."
    )

# ================== App bootstrap ==================

def main():
    if not TOKEN:
        raise SystemExit("BOT_TOKEN is not set.")
    app = Application.builder().token(TOKEN).build()
    # Slash commands (still supported)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
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
