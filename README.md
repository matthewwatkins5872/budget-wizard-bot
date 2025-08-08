
# Budget Wizard Telegram Bot (Railway, polling)

## Deploy on Railway
1. Create a new GitHub repo and add these files (`bot.py`, `requirements.txt`, `Procfile`).
2. Go to https://railway.app → New Project → Deploy from GitHub.
3. In Railway → Variables, add:
   - `BOT_TOKEN` = your Telegram bot token (from @BotFather)
   - `PAYPAL_LINK` = your PayPal.me link (optional), e.g. `https://paypal.me/YourName/1`
4. Deploy. Railway will start a **worker** process that runs `python bot.py`.
5. Open your bot in Telegram and send `/start`.

## Commands (set these in @BotFather → /setcommands)
start - Begin using Budget Wizard and see welcome instructions
addexpense - Add a new expense with amount, category, and optional notes
viewexpenses - View a summary of your recorded expenses
generatebudget - Create a budget report based on your expenses
exportexcel - Generate and download your Excel spreadsheet
unlockfull - Unlock the full detailed report for a small fee
help - View all commands and usage instructions

## Notes
- This uses in-memory storage; data resets when the process restarts. For persistence, replace STORE with a database.
- For PayPal auto-unlock, implement a webhook and verify payments, then mark users as "unlocked".
