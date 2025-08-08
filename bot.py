
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

def add_expense_to_store(user_id: int, amount: float, category: str, notes: str):
    STORE.setdefault(user_id, []).append({
        "amount": amount,
        "category": category,
        "notes": notes,
        "ts": datetime.utcnow()
    })

def get_expenses(user_id: int):
    return STORE.get(user_id, [])

# ===== Command handlers =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "Welcome to Budget Wizard 🧙‍♂️\n\n"
        "Commands:\n"
        "/addexpense <amount> <category> [notes]\n"
        "  e.g. /addexpense 12.50 groceries milk and bread\n"
        "/viewexpenses - Summary of your expenses\n"
        "/generatebudget - Simple budget snapshot\n"
        "/exportexcel - Download your expenses as an Excel file\n"
        "/unlockfull - Pay $1 to unlock detailed reports\n"
        "/help - Show this menu again"
    )
    await update.message.reply_text(msg)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def addexpense(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await update.message.reply_text(f"✅ Added ${amount:.2f} to '{category}'. Use /viewexpenses to see totals.")

async def viewexpenses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    items = get_expenses(user_id)
    if not items:
        return await update.message.reply_text("No expenses yet. Add one with /addexpense 12.50 groceries")
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
        return await update.message.reply_text("No data yet. Add expenses with /addexpense.")
    total = sum(x["amount"] for x in items)
    # A tiny demo "budget": recommend spending <= 70% of average daily spend
    days = max((datetime.utcnow() - min(x["ts"] for x in items)).days + 1, 1)
    avg_daily = total / days
    rec_daily = avg_daily * 0.7
    await update.message.reply_text(
        f"🧮 Budget snapshot:\n"
        f"- Avg daily spend: ${avg_daily:.2f}\n"
        f"- Suggested cap: ${rec_daily:.2f}/day\n"
        f"Use /exportexcel to download your data."
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
    filename = "budget_wizard_expenses.xlsx"
    await update.message.reply_document(InputFile(bio, filename), caption="Here is your Excel export.")

async def unlockfull(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Unlock the full detailed report for $1:\n"
        f"{PAYPAL_LINK}\n\n"
        "After payment, reply 'paid' and I'll unlock your report (demo)."
    )

async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text == "paid":
        await update.message.reply_text("✅ Payment noted (manual). Your full report is unlocked!")
    else:
        await update.message.reply_text("Type /start to see available commands.")

def main():
    if not TOKEN:
        raise SystemExit("BOT_TOKEN is not set.")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("addexpense", addexpense))
    app.add_handler(CommandHandler("viewexpenses", viewexpenses))
    app.add_handler(CommandHandler("generatebudget", generatebudget))
    app.add_handler(CommandHandler("exportexcel", exportexcel))
    app.add_handler(CommandHandler("unlockfull", unlockfull))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
