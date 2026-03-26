# config.py
import os

# ==================== BOT CONFIGURATION ====================
BOT_TOKEN = "8769141184:AAGKwez7pW89lLi2XUHwKbjNs0766v03mp4"  # Replace with your bot token

# ==================== API CONFIGURATION ====================
API_ENDPOINT = "https://yttttttt.anshapi.workers.dev/"
API_KEY = "DARKOSINT"

# ==================== MONGODB CONFIGURATION ====================
MONGODB_URI = "mongodb+srv://aztech:ayazahmed1122@cluster0.mhuaw3q.mongodb.net/num2info?retryWrites=true&w=majority"
DATABASE_NAME = "num2info"

# ==================== CHANNEL & GROUP CONFIGURATION ====================
FORCE_JOIN_CHANNEL_ID = -1002901487490
FORCE_JOIN_CHANNEL_LINK = "https://t.me/aztechshub"
ALLOWED_GROUP_ID = -1003629887048
ALLOWED_GROUP_LINK = "https://t.me/number2infogc"

# ==================== ADMIN CONFIGURATION ====================
ADMIN_USER_ID = 6670166083  # Replace with your Telegram user ID

# ==================== LIMITS ====================
# All users now have unlimited access
UNLIMITED_LOOKUPS = True

# ==================== MESSAGES (HTML FORMAT) ====================
WELCOME_MESSAGE = """
🔍 <b>Phone Intelligence Bot</b> 🔍

Welcome to the most advanced phone number lookup service!

📱 <b>Features:</b>
• Instant phone number intelligence
• Detailed personal information
• Address verification
• Network carrier details
• Alternative numbers

✨ <b>Unlimited searches for everyone!</b>

⚠️ <b>Note:</b> You must join our channel to use this bot.

👨‍💻 <b>Developer:</b> @AzTechDeveloper
"""

HELP_MESSAGE = """
📖 <b>Help Guide</b>

<b>Commands:</b>
/start - Welcome message
/help - This help guide

<b>How to use:</b>
1. Send any 10-digit Indian mobile number
2. Wait for the bot to fetch intelligence
3. Receive formatted results

<b>Example:</b> <code>8929162117</code>

<b>Support:</b> @AzTechDeveloper
"""

NOT_IN_GROUP = """
⛔ <b>Access Denied</b>

This bot only works in {group_link}.

Please use the bot in the allowed group only.
"""

FORCE_JOIN_MESSAGE = """
⚠️ <b>Join Channel Required</b>

To use this bot, you must join our channel first.

📢 <b>Channel:</b> {channel_link}

After joining, click the button below to verify!
"""

ALREADY_VERIFIED = """
✅ <b>You're all set!</b>

You have already joined the channel. You can now use the bot!
"""

ERROR_MESSAGES = {
    "invalid_number": "❌ <b>Invalid Number</b>\nPlease enter a valid 10-digit Indian mobile number (starting with 6,7,8,9).",
    "no_data": "🔍 <b>No Results Found</b>\nNo information available for this number. Please try another number.",
    "api_error": "🔍 <b>No Results Found</b>\nNo information available for this number. Please try another number.",
}

# Inline button labels
BTN_VERIFY_JOIN = "✅ Verify Joined"
BTN_JOIN_CHANNEL = "📢 Join Channel"
