# config.py
import os

# ==================== BOT CONFIGURATION ====================
BOT_TOKEN = "8769141184:AAEoxP61Uq3RLdldWGGvgc9-W6Pvu3eYKmA"

# ==================== API CONFIGURATION ====================
API_ENDPOINT = "https://yttttttt.anshapi.workers.dev/"
API_KEY = "DARKOSINT"

# Username to Number API Configuration
USERNAME_API_ENDPOINT = "https://username-to-number.vercel.app/"
USERNAME_API_KEY = "my_dayne"
USERNAME_LOOKUP_DAILY_LIMIT = 3  # 3 free searches per user per day

# ==================== MONGODB CONFIGURATION ====================
MONGODB_URI = "mongodb+srv://aztech:ayazahmed1122@cluster0.mhuaw3q.mongodb.net/num2info?retryWrites=true&w=majority"
DATABASE_NAME = "num2info"

# ==================== TELETHON CONFIGURATION ====================
# Get these from https://my.telegram.org → API Development Tools
TG_API_ID = 36570856          # ← Replace with your API ID (integer)
TG_API_HASH = "b7057ccac004db1d1bb9b5c5220e7f9d"       # ← Replace with your API Hash (string)

# ==================== CHANNEL & GROUP CONFIGURATION ====================
FORCE_JOIN_CHANNEL_ID = -1002901487490
FORCE_JOIN_CHANNEL_LINK = "https://t.me/aztechshub"
ALLOWED_GROUP_ID = -1003629887048
ALLOWED_GROUP_LINK = "https://t.me/number2infogc"

# ==================== ADMIN CONFIGURATION ====================
ADMIN_USER_ID = 6670166083

# ==================== PROTECTED USERS ====================
PROTECTED_USERNAMES = ["aztechdeveloper"]
PROTECTED_USER_IDS = ["6670166083"]

# ==================== LIMITS ====================
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
• Username to phone lookup (3/day)
• Instagram profile lookup

✨ <b>Unlimited phone searches for everyone!</b>

⚠️ <b>Note:</b> You must join our channel to use this bot.

👨‍💻 <b>Developer:</b> @AzTechDeveloper
"""

HELP_MESSAGE = """
📖 <b>Help Guide</b>

<b>Commands:</b>
/start - Welcome message
/help - This help guide
/ig @username - Instagram profile lookup

<b>How to use:</b>

📱 <b>Phone Number Lookup:</b>
1. Send any 10-digit Indian mobile number
2. Wait for the bot to fetch intelligence
3. Receive formatted results

👤 <b>Username/User ID Lookup:</b>
1. Send a Telegram username (e.g., @username)
2. Or send a Telegram user ID (e.g., 1234567890)
3. Get phone number details + full Telegram profile
4. Limited to 3 searches per day

📸 <b>Instagram Profile Lookup:</b>
1. Send an Instagram username (e.g., @username)
2. Or use /ig @username command
3. Get full Instagram profile details
4. Includes followers, following, posts, bio, and profile photo

<b>Examples:</b>
• Phone: <code>8929162117</code>
• Username: <code>@telegram</code>
• User ID: <code>1234567890</code>
• Instagram: <code>@instagram</code>

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
    "daily_limit_exceeded": "⛔ <b>Daily Limit Exceeded</b>\n\nYou have reached your daily limit of {limit} username/user ID lookups.\n\nPlease try again tomorrow!",
    "username_not_found": "❌ <b>Username Not Found</b>\n\nCould not find the username @{username}.\n\nPlease check the username and try again.",
    "no_username_data": "🔍 <b>No Data Found</b>\n\nNo phone information available for this user ID.\n\nThe user may not have linked their phone number.",
}

# Inline button labels
BTN_VERIFY_JOIN = "✅ Verify Joined"
BTN_JOIN_CHANNEL = "📢 Join Channel"
