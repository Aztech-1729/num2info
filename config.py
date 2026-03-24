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

# ==================== PRICING & LIMITS ====================
FREE_DAILY_LIMIT = 3
PREMIUM_PRICE = 29  # INR per day
PREMIUM_DAILY_LIMIT = 999999  # effectively unlimited
PREMIUM_DURATION_HOURS = 24

# ==================== UPI & PAYMENT ====================
UPI_ID = "aztech7@axl"  # Replace with your actual UPI ID
QR_IMAGE_URL = "https://i.ibb.co/VWWVVfrD/qr.jpg"

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

💰 <b>Pricing:</b>
• FREE: 3 lookups per day
• PREMIUM: ₹29/day - Unlimited lookups

⚠️ <b>Note:</b> You must join our channel to use this bot.

👨‍💻 <b>Developer:</b> @AzTechDeveloper
"""

HELP_MESSAGE = """
📖 <b>Help Guide</b>

<b>Commands:</b>
/start - Welcome message
/help - This help guide
/status - Check your remaining lookups

<b>How to use:</b>
1. Send any 10-digit Indian mobile number
2. Wait for the bot to fetch intelligence
3. Receive formatted results

<b>Example:</b> <code>8929162117</code>

<b>Premium Access:</b>
Pay ₹29 via UPI and send screenshot to admin

<b>Support:</b> @AzTechDeveloper
"""

PREMIUM_INFO = """
💎 <b>Premium Access</b> 💎

<b>Benefits:</b>
✨ Unlimited daily lookups
✨ Priority processing
✨ No daily limits
✨ Full data access

<b>Price:</b> ₹29 per day

<b>How to Pay:</b>
1. Send ₹29 to UPI ID: <code>{upi_id}</code>
2. Take a screenshot of payment
3. Send the screenshot here

<b>After Payment:</b>
Your account will be upgraded instantly with unlimited access for 24 hours!

<b>Questions?</b> Contact @AzTechDeveloper
"""

LIMIT_EXCEEDED_MESSAGE = """
🚫 <b>Daily Limit Reached</b>

You have used all your {limit} free lookups today.

💎 <b>Upgrade to Premium:</b>
• Price: ₹{price}/day
• Unlimited lookups
• 24 hours validity

Click below to purchase!
"""

PAYMENT_INSTRUCTIONS = """
💳 <b>Payment Instructions</b>

Send ₹{price} to UPI ID:
<code>{upi_id}</code>

📷 <b>After payment:</b>
Take a screenshot and send it here.

⏰ Payment will be verified within 24 hours.
"""

PAYMENT_CANCELLED = "❌ <b>Payment Cancelled</b>\n\nYou can try again anytime with /premium"

SCREENSHOT_REQUEST = """
📷 <b>Send Payment Screenshot</b>

Please send a screenshot of your payment confirmation.
"""

PAYMENT_REVIEW = """
💰 <b>Payment Pending Review</b>

📱 <b>UPI ID:</b> <code>{upi_id}</code>
💵 <b>Amount:</b> ₹{price}
⏰ Please wait while we verify your payment.
"""

PREMIUM_APPROVED = """
🎉 <b>Payment Verified!</b>

💎 <b>Premium Activated!</b>
✨ Unlimited lookups for 24 hours!

Thank you for your purchase! 🎊
"""

PREMIUM_REJECTED = """
❌ <b>Payment Rejected</b>

Your payment could not be verified. Please try again or contact @AzTechDeveloper
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
    "no_data": "❌ <b>No Data Found</b>\nNo intelligence records available for this number.",
    "api_error": "⚠️ <b>API Error</b>\nThe intelligence service is temporarily unavailable. Please try again later.",
    "limit_reached": "🚫 <b>Daily Limit Reached</b>\nYou have used all your free lookups today.\nUpgrade to premium with /premium for unlimited access!",
    "premium_expired": "⏰ <b>Premium Expired</b>\nYour premium access has expired.\nUse /premium to renew for ₹29/day!",
}

# Inline button labels
BTN_VERIFY_JOIN = "✅ Verify Joined"
BTN_JOIN_CHANNEL = "📢 Join Channel"
BTN_BUY_NOW = "💎 Buy Now - ₹29"
BTN_CANCEL = "❌ Cancel"
BTN_APPROVE = "✅ Approve"
BTN_REJECT = "❌ Reject"