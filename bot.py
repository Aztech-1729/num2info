# bot.py
import asyncio
import logging
import re
import sys
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

# Fix for Windows/asyncio issues
import nest_asyncio
nest_asyncio.apply()

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
)
from pymongo import MongoClient
import config

# Configure logging - reduce httpx spam
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
# Reduce httpx log spam
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext._httpxrequest").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


# ==================== DATABASE ====================
class Database:
    def __init__(self):
        try:
            self.client = MongoClient(config.MONGODB_URI)
            self.db = self.client[config.DATABASE_NAME]
            self.users = self.db.users
            self.pending_payments = self.db.pending_payments
            self.verified_members = self.db.verified_members
            # Create indexes synchronously at startup
            self._create_indexes()
            logger.info("MongoDB connected successfully")
        except Exception as e:
            logger.error(f"MongoDB connection failed: {e}")
            raise

    def _create_indexes(self):
        """Create indexes for better performance"""
        self.users.create_index("user_id", unique=True)
        self.users.create_index("premium_expires_at")
        self.pending_payments.create_index("user_id")
        self.pending_payments.create_index("timestamp")
        self.verified_members.create_index("user_id", unique=True)

    async def get_user(self, user_id: int) -> Dict:
        """Get user data or create if not exists"""
        user = self.users.find_one({"user_id": user_id})
        if not user:
            user = {
                "user_id": user_id,
                "daily_used": 0,
                "last_reset_date": datetime.utcnow().date().isoformat(),
                "premium_expires_at": None,
                "total_lookups": 0,
                "joined_date": datetime.utcnow(),
            }
            self.users.insert_one(user)
        return user

    async def update_user_lookup(self, user_id: int) -> bool:
        """Update user lookup count, returns True if allowed"""
        user = await self.get_user(user_id)
        today = datetime.utcnow().date().isoformat()

        # Check premium status
        if user.get("premium_expires_at"):
            expires_at = user["premium_expires_at"]
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            if expires_at > datetime.utcnow():
                # Premium user - unlimited
                self.users.update_one(
                    {"user_id": user_id},
                    {
                        "$inc": {"total_lookups": 1},
                        "$set": {"last_activity": datetime.utcnow()},
                    },
                )
                return True

        # Free user - check daily limit
        if user["last_reset_date"] != today:
            # Reset daily count
            self.users.update_one(
                {"user_id": user_id},
                {
                    "$set": {"daily_used": 0, "last_reset_date": today},
                    "$inc": {"total_lookups": 1},
                },
            )
            return True

        if user["daily_used"] < config.FREE_DAILY_LIMIT:
            self.users.update_one(
                {"user_id": user_id},
                {"$inc": {"daily_used": 1, "total_lookups": 1}},
            )
            return True

        return False

    async def get_remaining_lookups(self, user_id: int) -> Tuple[int, Optional[datetime]]:
        """Get remaining lookups for today and premium expiry"""
        user = await self.get_user(user_id)
        today = datetime.utcnow().date().isoformat()

        # Check premium
        if user.get("premium_expires_at"):
            expires_at = user["premium_expires_at"]
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            if expires_at > datetime.utcnow():
                return config.PREMIUM_DAILY_LIMIT, expires_at

        # Free user
        if user["last_reset_date"] != today:
            return config.FREE_DAILY_LIMIT, None

        remaining = max(0, config.FREE_DAILY_LIMIT - user["daily_used"])
        return remaining, None

    async def activate_premium(self, user_id: int, hours: int = 24) -> bool:
        """Activate premium for user"""
        try:
            expires_at = datetime.utcnow() + timedelta(hours=hours)
            self.users.update_one(
                {"user_id": user_id},
                {
                    "$set": {"premium_expires_at": expires_at},
                },
            )
            return True
        except Exception as e:
            logger.error(f"Premium activation failed: {e}")
            return False

    async def save_pending_payment(self, user_id: int, photo_file_id: str) -> bool:
        """Save pending payment for admin review"""
        try:
            self.pending_payments.insert_one({
                "user_id": user_id,
                "photo_file_id": photo_file_id,
                "timestamp": datetime.utcnow(),
                "status": "pending"
            })
            return True
        except Exception as e:
            logger.error(f"Payment save failed: {e}")
            return False

    async def get_pending_payments(self) -> list:
        """Get all pending payments"""
        return list(self.pending_payments.find({"status": "pending"}))

    async def approve_payment(self, user_id: int) -> bool:
        """Approve a payment and activate premium"""
        try:
            self.pending_payments.update_one(
                {"user_id": user_id, "status": "pending"},
                {"$set": {"status": "approved", "approved_at": datetime.utcnow()}}
            )
            await self.activate_premium(user_id, config.PREMIUM_DURATION_HOURS)
            return True
        except Exception as e:
            logger.error(f"Payment approval failed: {e}")
            return False

    async def reject_payment(self, user_id: int) -> bool:
        """Reject a payment"""
        try:
            self.pending_payments.update_one(
                {"user_id": user_id, "status": "pending"},
                {"$set": {"status": "rejected", "rejected_at": datetime.utcnow()}}
            )
            return True
        except Exception as e:
            logger.error(f"Payment rejection failed: {e}")
            return False

    async def is_member_verified(self, user_id: int) -> bool:
        """Check if user is verified (joined channel)"""
        return self.verified_members.find_one({"user_id": user_id}) is not None

    async def mark_member_verified(self, user_id: int) -> bool:
        """Mark user as verified (joined channel)"""
        try:
            self.verified_members.update_one(
                {"user_id": user_id},
                {"$set": {"verified_at": datetime.utcnow()}},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Mark verified failed: {e}")
            return False


# ==================== BOT CLASS ====================
class PhoneIntelligenceBot:
    def __init__(self):
        self.db = Database()
        self.api_endpoint = config.API_ENDPOINT
        self.api_key = config.API_KEY
        self._user_states = {}  # Track user states for screenshots
        self._awaiting_screenshot = set()  # Users who clicked buy and awaiting screenshot

    @staticmethod
    def validate_phone_number(number: str) -> bool:
        """Validate Indian mobile number"""
        pattern = r"^[6-9]\d{9}$"
        return bool(re.match(pattern, number.strip()))

    async def fetch_phone_data(self, phone_number: str) -> Optional[Dict]:
        """Fetch data from the intelligence API"""
        try:
            async with aiohttp.ClientSession() as session:
                params = {"key": self.api_key, "num": phone_number}
                async with session.get(self.api_endpoint, params=params, timeout=15) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("success") and data.get("result"):
                            return data
                    return None
        except Exception as e:
            logger.error(f"API fetch error: {e}")
            return None

    def format_response(self, data: Dict, phone_number: str) -> str:
        """Format the API response into beautiful HTML message"""
        results = data.get("result", [])
        if not results:
            return config.ERROR_MESSAGES["no_data"]
        
        # Build message with HTML tags
        formatted = "<b>🔍 Phone Intelligence Report</b>\n"
        formatted += f"<b>📱 Number:</b> <code>{phone_number}</code>\n"
        formatted += "=" * 35 + "\n\n"

        for idx, result in enumerate(results, 1):
            if len(results) > 1:
                formatted += f"<b>📌 Result {idx}</b>\n"
                formatted += "─" * 25 + "\n"

            # Name
            if result.get("name"):
                name = str(result['name']).replace('<', '').replace('>', '')
                formatted += f"👤 <b>Name:</b> {name}\n"

            # Father/Husband
            if result.get("father_name"):
                fname = str(result['father_name']).replace('<', '').replace('>', '')
                formatted += f"👨 <b>Father/Husband:</b> {fname}\n"

            # Address
            if result.get("address"):
                address = str(result['address']).replace('\n', ' ').replace('<', '').replace('>', '')
                formatted += f"📍 <b>Address:</b> {address}\n"

            # Alternative Mobile
            if result.get("alt_mobile"):
                alt = str(result['alt_mobile']).replace('<', '').replace('>', '')
                formatted += f"📞 <b>Alt Mobile:</b> <code>{alt}</code>\n"

            # Circle/Network
            if result.get("circle"):
                circle = str(result['circle']).replace('<', '').replace('>', '')
                formatted += f"📡 <b>Network:</b> {circle}\n"

            # Email
            if result.get("email"):
                email = str(result['email']).replace('<', '').replace('>', '')
                formatted += f"✉️ <b>Email:</b> {email}\n"

            # ID Number
            if result.get("id_number"):
                id_num = str(result['id_number']).replace('<', '').replace('>', '')
                formatted += f"🆔 <b>ID:</b> <code>{id_num}</code>\n"

            formatted += "\n"

        formatted += "=" * 35 + "\n"
        formatted += f"🔮 <b>Powered by:</b> @AzTechDeveloper\n"
        return formatted

    async def check_channel_membership(self, user_id: int, bot_instance) -> bool:
        """Check if user is member of the required channel"""
        try:
            chat_member = await bot_instance.get_chat_member(
                config.FORCE_JOIN_CHANNEL_ID,
                user_id
            )
            return chat_member.status in ['member', 'administrator', 'creator']
        except Exception as e:
            logger.error(f"Channel membership check failed: {e}")
            return False

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        await self.db.get_user(user.id)

        # Check if in allowed group
        if update.effective_chat.id != config.ALLOWED_GROUP_ID:
            await update.message.reply_text(
                config.NOT_IN_GROUP.format(group_link=config.ALLOWED_GROUP_LINK),
                parse_mode="HTML"
            )
            return

        welcome_msg = config.WELCOME_MESSAGE

        keyboard = [
            [InlineKeyboardButton("📊 Check Status", callback_data="status")],
            [InlineKeyboardButton("💎 Get Premium", callback_data="premium")],
            [InlineKeyboardButton("❓ Help", callback_data="help")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(welcome_msg, parse_mode="HTML", reply_markup=reply_markup)

    async def handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        # Check group
        if update.effective_chat.id != config.ALLOWED_GROUP_ID:
            return

        await update.message.reply_text(config.HELP_MESSAGE, parse_mode="HTML")

    async def handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        # Check group
        if update.effective_chat.id != config.ALLOWED_GROUP_ID:
            return

        user_id = update.effective_user.id
        remaining, expires_at = await self.db.get_remaining_lookups(user_id)

        status_msg = f"📊 *Your Status*\n\n"
        if expires_at and expires_at > datetime.utcnow():
            expiry_str = expires_at.strftime("%Y-%m-%d %H:%M:%S UTC")
            status_msg += f"💎 *Plan:* Premium\n"
            status_msg += f"✨ *Lookups:* Unlimited\n"
            status_msg += f"⏰ *Expires:* `{expiry_str}`\n"
        else:
            status_msg += f"🎁 *Plan:* Free\n"
            status_msg += f"🔍 *Remaining Today:* {remaining}/{config.FREE_DAILY_LIMIT}\n"
            status_msg += f"\n💎 Upgrade to premium for unlimited lookups!\n"
            status_msg += f"Use /premium for details."

        await update.message.reply_text(status_msg, parse_mode="HTML")

    async def handle_premium(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /premium command"""
        # Check group
        if update.effective_chat.id != config.ALLOWED_GROUP_ID:
            return

        await self.show_premium_info(update, None)

    async def handle_grant(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /grant command (admin only) - grant or revoke premium"""
        user_id = update.effective_user.id
        
        # Check if admin
        if user_id != config.ADMIN_USER_ID:
            await update.message.reply_text(
                "⛔ <b>Access Denied</b>\nThis command is for administrators only.",
                parse_mode="HTML"
            )
            return
        
        # Check arguments
        if len(context.args) != 2:
            await update.message.reply_text(
                "⚠️ <b>Usage:\u003c/b>\n<code>/grant userid y\u003c/code> - Grant 1 day premium\n<code>/grant userid n\u003c/code> - Revoke premium",
                parse_mode="HTML"
            )
            return
        
        target_user_id = context.args[0]
        action = context.args[1].lower()
        
        # Validate user_id
        try:
            target_user_id = int(target_user_id)
        except ValueError:
            await update.message.reply_text(
                "❌ <b>Invalid User ID</b>\nPlease provide a valid numeric user ID.",
                parse_mode="HTML"
            )
            return
        
        if action == 'y':
            # Grant 1 day premium
            await self.db.activate_premium(target_user_id, 24)
            await update.message.reply_text(
                f"✅ <b>Premium Granted!</b>\n\nUser ID: <code>{target_user_id}</code>\nDuration: 24 hours",
                parse_mode="HTML"
            )
            # Notify user
            try:
                await context.bot.send_message(
                    target_user_id,
                    "🎉 <b>Premium Activated!</b>\n\nYou have been granted 24 hours of premium access by admin.\n\n✨ Enjoy unlimited lookups!",
                    parse_mode="HTML"
                )
            except:
                pass
                
        elif action == 'n':
            # Revoke premium
            await self.db.activate_premium(target_user_id, 0)  # Expire immediately
            await update.message.reply_text(
                f"✅ <b>Premium Revoked!</b>\n\nUser ID: <code>{target_user_id}</code>",
                parse_mode="HTML"
            )
            # Notify user
            try:
                await context.bot.send_message(
                    target_user_id,
                    "⚠️ <b>Premium Revoked</b>\n\nYour premium access has been revoked by admin.",
                    parse_mode="HTML"
                )
            except:
                pass
        else:
            await update.message.reply_text(
                "⚠️ <b>Invalid Action</b>\nUse \u003ccode>y\u003c/code> to grant or \u003ccode>n\u003c/code> to revoke.",
                parse_mode="HTML"
            )

    async def show_premium_info(self, update: Update, query):
        """Show premium information with payment QR in single message"""
        # Create inline keyboard
        keyboard = [
            [InlineKeyboardButton(config.BTN_BUY_NOW, callback_data="buy_premium")],
            [InlineKeyboardButton(config.BTN_CANCEL, callback_data="cancel_premium")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Send only QR with complete info in caption
        if query:
            try:
                await query.message.delete()
            except:
                pass
            await query.message.chat.send_photo(
                photo=config.QR_IMAGE_URL,
                caption=f"""💎 *Premium Access* 💎

*Benefits:*
✨ Unlimited daily lookups
✨ Priority processing
✨ No daily limits
✨ Full data access

*Price:* ₹{config.PREMIUM_PRICE}/day

📱 *UPI ID:* `{config.UPI_ID}`

*How to Pay:*
1. Scan QR above to pay ₹{config.PREMIUM_PRICE}
2. Take screenshot
3. Send screenshot here

*Questions?* @AzTechDeveloper""",
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        else:
            await update.message.chat.send_photo(
                photo=config.QR_IMAGE_URL,
                caption=f"""💎 *Premium Access* 💎

*Benefits:*
✨ Unlimited daily lookups
✨ Priority processing
✨ No daily limits
✨ Full data access

*Price:* ₹{config.PREMIUM_PRICE}/day

📱 *UPI ID:* `{config.UPI_ID}`

*How to Pay:*
1. Scan QR above to pay ₹{config.PREMIUM_PRICE}
2. Take screenshot
3. Send screenshot here

*Questions?* @AzTechDeveloper""",
                parse_mode="HTML",
                reply_markup=reply_markup
            )

    async def show_payment_instructions(self, update: Update, query=None):
        """Show payment instructions with cancel button"""
        # Add user to awaiting screenshot set
        if query:
            user_id = query.from_user.id
            chat_id = query.message.chat.id
        else:
            user_id = update.effective_user.id
            chat_id = update.effective_chat.id
        
        self._awaiting_screenshot.add(user_id)
        
        keyboard = [
            [InlineKeyboardButton(config.BTN_CANCEL, callback_data="cancel_payment")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if query:
            try:
                await query.edit_message_text(
                    f"📱 *Scan QR to Pay ₹{config.PREMIUM_PRICE}*\n\nUPI ID: `{config.UPI_ID}`\n\n💳 *After payment, send screenshot here*",
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
            except:
                await query.message.reply_text(
                    f"📱 *Scan QR to Pay ₹{config.PREMIUM_PRICE}*\n\nUPI ID: `{config.UPI_ID}`\n\n💳 *After payment, send screenshot here*",
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
            await query.message.reply_photo(
                photo=config.QR_IMAGE_URL,
                parse_mode="HTML"
            )
        else:
            sent_msg = await update.message.reply_text(
                f"📱 *Scan QR to Pay ₹{config.PREMIUM_PRICE}*\n\nUPI ID: `{config.UPI_ID}`\n\n💳 *After payment, send screenshot here*",
                parse_mode="HTML",
                reply_markup=reply_markup
            )
            await update.message.reply_photo(
                photo=config.QR_IMAGE_URL,
                parse_mode="HTML"
            )
            return sent_msg

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline keyboard callbacks"""
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        bot = context.bot

        # Check group for non-admin callbacks (allow approve/reject in DM too)
        if not query.data.startswith("approve_payment_") and not query.data.startswith("reject_payment_"):
            if query.message.chat.id != config.ALLOWED_GROUP_ID:
                await query.answer("This bot only works in the allowed group!", show_alert=True)
                return

        if query.data == "status":
            remaining, expires_at = await self.db.get_remaining_lookups(user_id)

            status_msg = f"📊 <b>Your Status</b>\n\n"
            if expires_at and expires_at > datetime.utcnow():
                expiry_str = expires_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                status_msg += f"💎 <b>Plan:</b> Premium\n"
                status_msg += f"✨ <b>Lookups:</b> Unlimited\n"
                status_msg += f"⏰ <b>Expires:</b> <code>{expiry_str}</code>\n"
            else:
                status_msg += f"🎁 <b>Plan:</b> Free\n"
                status_msg += f"🔍 <b>Remaining Today:</b> {remaining}/{config.FREE_DAILY_LIMIT}\n"
                status_msg += f"\n💎 Upgrade to premium for unlimited lookups!\n"
                status_msg += f"Use /premium for details."

            await query.edit_message_text(status_msg, parse_mode="HTML")

        elif query.data == "premium":
            await self.show_premium_info(update, query)

        elif query.data == "help":
            await query.edit_message_text(config.HELP_MESSAGE, parse_mode="HTML")

        elif query.data == "buy_premium":
            # Show QR when user clicks Buy Now - REPLACE media instead of delete+send
            user_id = query.from_user.id
            self._awaiting_screenshot.add(user_id)
            
            keyboard = [
                [InlineKeyboardButton(config.BTN_CANCEL, callback_data="cancel_payment")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Replace the message with QR
            await query.edit_message_media(
                media=InputMediaPhoto(
                    media=config.QR_IMAGE_URL,
                    caption=f"""📱 *Scan QR to Pay ₹{config.PREMIUM_PRICE}*

UPI ID: `{config.UPI_ID}`

💳 *After payment, send screenshot here*""",
                    parse_mode="HTML"
                ),
                reply_markup=reply_markup
            )

        elif query.data == "cancel_payment":
            payment_msg = query.message
            chat_id = payment_msg.chat.id
            user_id = query.from_user.id
            self._awaiting_screenshot.discard(user_id)  # Remove from awaiting
            try:
                await payment_msg.delete()
            except:
                pass
            await context.bot.send_message(
                chat_id=chat_id,
                text=config.PAYMENT_CANCELLED,
                parse_mode="HTML"
            )

        elif query.data == "cancel_limit":
            user_id = query.from_user.id
            self._awaiting_screenshot.discard(user_id)
            try:
                await query.message.delete()
            except:
                pass
            await context.bot.send_message(
                chat_id=query.message.chat.id,
                text="✅ *OK*\n\nYou can continue using free lookups. Use /premium anytime to upgrade.",
                parse_mode="HTML"
            )

        elif query.data == "cancel_premium":
            user_id = query.from_user.id
            self._awaiting_screenshot.discard(user_id)
            try:
                await query.message.delete()
            except:
                pass
            await context.bot.send_message(
                chat_id=query.message.chat.id,
                text="✅ *Cancelled*\n\nUse /premium anytime to purchase premium.",
                parse_mode="HTML"
            )

        elif query.data == "verify_join":
            # Check if user joined channel
            is_member = await self.check_channel_membership(user_id, context.bot)
            if is_member:
                await self.db.mark_member_verified(user_id)
                try:
                    await query.message.delete()
                except:
                    pass
                await context.bot.send_message(
                    chat_id=query.message.chat.id,
                    text=config.ALREADY_VERIFIED,
                    parse_mode="HTML"
                )
            else:
                keyboard = [
                    [InlineKeyboardButton(config.BTN_JOIN_CHANNEL, url=config.FORCE_JOIN_CHANNEL_LINK)],
                    [InlineKeyboardButton(config.BTN_VERIFY_JOIN, callback_data="verify_join")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                try:
                    await query.edit_message_text(
                        config.FORCE_JOIN_MESSAGE.format(channel_link=config.FORCE_JOIN_CHANNEL_LINK),
                        parse_mode="HTML",
                        reply_markup=reply_markup
                    )
                except:
                    pass  # Message not modified or other error

        elif query.data.startswith("approve_payment_"):
            # Admin only
            payment_user_id = int(query.data.split("_")[-1])
            if user_id != config.ADMIN_USER_ID:
                await query.answer("Unauthorized!", show_alert=True)
                return

            await self.db.approve_payment(payment_user_id)

            # Notify user
            try:
                await bot.send_message(
                    payment_user_id,
                    config.PREMIUM_APPROVED,
                    parse_mode="HTML"
                )
            except:
                pass

            # Update admin message
            await query.edit_message_text(
                f"✅ <b>Payment Approved</b>\n\nUser ID: <code>{payment_user_id}</code>\nPremium activated!",
                parse_mode="HTML"
            )

        elif query.data.startswith("reject_payment_"):
            # Admin only
            payment_user_id = int(query.data.split("_")[-1])
            if user_id != config.ADMIN_USER_ID:
                await query.answer("Unauthorized!", show_alert=True)
                return

            await self.db.reject_payment(payment_user_id)

            # Notify user
            try:
                await bot.send_message(
                    payment_user_id,
                    config.PREMIUM_REJECTED,
                    parse_mode="HTML"
                )
            except:
                pass

            # Update admin message
            await query.edit_message_text(
                f"❌ <b>Payment Rejected</b>\n\nUser ID: <code>{payment_user_id}</code>",
                parse_mode="HTML"
            )

    async def handle_phone_number(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle phone number messages"""
        # Only allowed in group
        if update.effective_chat.id != config.ALLOWED_GROUP_ID:
            return

        user_id = update.effective_user.id
        phone_number = update.message.text.strip()

        # Validate phone number
        if not self.validate_phone_number(phone_number):
            await update.message.reply_text(
                config.ERROR_MESSAGES["invalid_number"],
                parse_mode="HTML"
            )
            return

        # Check channel membership
        is_verified = await self.db.is_member_verified(user_id)
        is_member = await self.check_channel_membership(user_id, context.bot)

        if not is_member:
            keyboard = [
                [InlineKeyboardButton(config.BTN_JOIN_CHANNEL, url=config.FORCE_JOIN_CHANNEL_LINK)],
                [InlineKeyboardButton(config.BTN_VERIFY_JOIN, callback_data="verify_join")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                config.FORCE_JOIN_MESSAGE.format(channel_link=config.FORCE_JOIN_CHANNEL_LINK),
                parse_mode="HTML",
                reply_markup=reply_markup
            )
            return

        # Update verified status if not already
        if not is_verified:
            await self.db.mark_member_verified(user_id)

        # Get remaining before checking
        remaining, expires_at = await self.db.get_remaining_lookups(user_id)

        # Check limit - ADMIN BYPASS
        if user_id == config.ADMIN_USER_ID:
            # Admin gets unlimited lifetime searches
            await self.db.update_user_lookup(user_id)  # Still track for stats
        else:
            # Regular user - check limits
            allowed = await self.db.update_user_lookup(user_id)
            if not allowed:
                if expires_at and expires_at <= datetime.utcnow():
                    await update.message.reply_text(
                        config.ERROR_MESSAGES["premium_expired"],
                        parse_mode="HTML"
                    )
                else:
                    # Show limit exceeded - one photo message with QR and buttons
                    keyboard = [
                        [InlineKeyboardButton(config.BTN_BUY_NOW, callback_data="buy_premium")],
                        [InlineKeyboardButton(config.BTN_CANCEL, callback_data="cancel_limit")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                    await update.message.reply_photo(
                        photo=config.QR_IMAGE_URL,
                        caption=f"""🚫 <b>Daily Limit Reached</b>

You have used all your 3 free lookups today.

💎 <b>Upgrade to Premium:</b>
• Price: ₹29/day
• Unlimited lookups
• 24 hours validity

📱 <code>UPI ID: {config.UPI_ID}</code>

💳 <b>After payment, send screenshot here</b>""",
                        parse_mode="HTML",
                        reply_markup=reply_markup
                    )
                return

        # Send typing indicator
        await update.message.chat.send_action(action="typing")

        # Fetch data
        data = await self.fetch_phone_data(phone_number)

        if not data:
            await update.message.reply_text(
                config.ERROR_MESSAGES["api_error"],
                parse_mode="HTML"
            )
            return

        # Format and send response
        response = self.format_response(data, phone_number)

        # Add remaining lookups info (show unlimited for admin)
        new_remaining, expires_at = await self.db.get_remaining_lookups(user_id)
        if user_id == config.ADMIN_USER_ID:
            response += "\n📊 \u003cb\u003eAdmin Access\u003c/b\u003e\n✨ Unlimited searches"
        elif not (expires_at and expires_at > datetime.utcnow()):
            if new_remaining > 0:
                response += f"\n📊 \u003cb>Remaining today:\u003c/b> {new_remaining}/{config.FREE_DAILY_LIMIT}\n"
            response += f"💎 Upgrade to premium: /premium"

        await update.message.reply_text(response, parse_mode="HTML")

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle photo messages (payment screenshots)"""
        # Only allowed in group
        if update.effective_chat.id != config.ALLOWED_GROUP_ID:
            return

        user_id = update.effective_user.id
        photo = update.message.photo

        if not photo:
            return

        # Only accept screenshots from users who clicked buy_premium
        if user_id not in self._awaiting_screenshot:
            return  # Ignore other photos in group

        # Get the largest photo (last in array)
        photo_file_id = photo[-1].file_id

        # Check if user has pending payment
        pending = await self.db.get_pending_payments()
        has_pending = any(p.get("user_id") == user_id and p.get("status") == "pending" for p in pending)

        if has_pending:
            await update.message.reply_text(
                "⏰ You already have a pending payment. Please wait for verification.",
                parse_mode="HTML"
            )
            return

        # Save pending payment
        await self.db.save_pending_payment(user_id, photo_file_id)
        
        # Remove from awaiting screenshot set
        self._awaiting_screenshot.discard(user_id)

        # Forward to admin
        keyboard = [
            [
                InlineKeyboardButton(config.BTN_APPROVE, callback_data=f"approve_payment_{user_id}"),
                InlineKeyboardButton(config.BTN_REJECT, callback_data=f"reject_payment_{user_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_photo(
            config.ADMIN_USER_ID,
            photo_file_id,
            caption=f"💰 *New Payment Submission*\n\nUser: @{update.effective_user.username or 'N/A'}\nUser ID: {user_id}\nAmount: ₹{config.PREMIUM_PRICE}",
            parse_mode="HTML",
            reply_markup=reply_markup
        )

        # Confirm to user
        await update.message.reply_text(
            config.PAYMENT_REVIEW.format(
                upi_id=config.UPI_ID,
                price=config.PREMIUM_PRICE
            ),
            parse_mode="HTML"
        )


# ==================== MAIN ====================
async def main():
    """Main bot function"""
    # Initialize bot
    bot_instance = PhoneIntelligenceBot()
    application = Application.builder().token(config.BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", bot_instance.handle_start))
    application.add_handler(CommandHandler("help", bot_instance.handle_help))
    application.add_handler(CommandHandler("status", bot_instance.handle_status))
    application.add_handler(CommandHandler("premium", bot_instance.handle_premium))
    application.add_handler(CommandHandler("grant", bot_instance.handle_grant))
    application.add_handler(CallbackQueryHandler(bot_instance.handle_callback))
    application.add_handler(MessageHandler(filters.PHOTO, bot_instance.handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot_instance.handle_phone_number))

    # Start bot
    logger.info("Bot is starting...")
    logger.info(f"Allowed Group ID: {config.ALLOWED_GROUP_ID}")
    logger.info(f"Required Channel ID: {config.FORCE_JOIN_CHANNEL_ID}")
    
    # Run with graceful shutdown
    try:
        await application.run_polling(drop_pending_updates=True)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down bot...")
        await application.stop()
    except Exception as e:
        logger.error(f"Bot error: {e}")
        await application.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped.")
    except RuntimeError as e:
        if "This event loop is already running" in str(e):
            # Fallback for environments with nested event loops
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(main())
            finally:
                pass
        else:
            raise
    except Exception as e:
        logger.error(f"Main error: {e}")