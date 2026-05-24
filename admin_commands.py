from telegram import Update
from telegram.ext import ContextTypes
from subscription import subscription_manager

ADMIN_USER_ID = 6733032506

async def is_admin(user_id):
    return user_id == ADMIN_USER_ID

async def admin_add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Accès refusé.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /admin_add_user <user_id> <username> [days]")
        return
    try:
        user_id = int(context.args[0])
        username = context.args[1]
        days = int(context.args[2]) if len(context.args) > 2 else 30
        success = subscription_manager.add_user(user_id, username, days)
        if success:
            await update.message.reply_text(f"✅ User {username} ({user_id}) ajouté pour {days} jours.")
    except ValueError:
        await update.message.reply_text("❌ Format invalide.")

async def admin_remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Accès refusé.")
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /admin_remove_user <user_id>")
        return
    try:
        user_id = int(context.args[0])
        success = subscription_manager.remove_user(user_id)
        if success:
            await update.message.reply_text(f"✅ Accès révoqué pour {user_id}.")
    except ValueError:
        await update.message.reply_text("❌ Format invalide.")

async def admin_list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Accès refusé.")
        return
    users = subscription_manager.get_all_users()
    if not users:
        await update.message.reply_text("❌ Aucun user.")
        return
    message = "📋 **USERS:**\n\n"
    for user_id, username, status, expiry in users:
        message += f"• {username} ({user_id}) - {status}\n  Expiry: {expiry}\n\n"
    await update.message.reply_text(message, parse_mode="Markdown")

async def admin_user_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Accès refusé.")
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /admin_status <user_id>")
        return
    try:
        user_id = int(context.args[0])
        users = subscription_manager.get_all_users()
        user_data = next((u for u in users if u[0] == user_id), None)
        if not user_data:
            await update.message.reply_text(f"❌ User {user_id} non trouvé.")
            return
        uid, username, status, expiry = user_data
        message = f"📊 **{username}:**\n• Status: {status}\n• Expiry: {expiry}"
        await update.message.reply_text(message, parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ Format invalide.")

async def admin_renew_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Accès refusé.")
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /admin_renew <user_id> [days]")
        return
    try:
        user_id = int(context.args[0])
        days = int(context.args[1]) if len(context.args) > 1 else 30
        success = subscription_manager.renew_subscription(user_id, days)
        if success:
            await update.message.reply_text(f"✅ Renouvelé pour {user_id} ({days} jours).")
    except ValueError:
        await update.message.reply_text("❌ Format invalide.")
