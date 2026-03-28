# bot.py
import asyncio
import logging
import re
from datetime import datetime, timezone

# Fix for Windows/asyncio issues
import nest_asyncio
nest_asyncio.apply()

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram.ext._httpxrequest").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.Updater").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
# Suppress timeout errors during shutdown
logging.getLogger("telegram.ext._updater").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)


# ==================== DATABASE ====================
class Database:
    def __init__(self):
        try:
            self.client = MongoClient(config.MONGODB_URI)
            self.db = self.client[config.DATABASE_NAME]
            self.users = self.db.users
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
        self.verified_members.create_index("user_id", unique=True)

    async def get_user(self, user_id: int):
        """Get user data or create if not exists"""
        user = self.users.find_one({"user_id": user_id})
        if not user:
            user = {
                "user_id": user_id,
                "total_lookups": 0,
                "joined_date": datetime.now(timezone.utc),
            }
            self.users.insert_one(user)
        return user

    async def update_user_lookup(self, user_id: int):
        """Update user lookup count - now unlimited for all"""
        self.users.update_one(
            {"user_id": user_id},
            {
                "$inc": {"total_lookups": 1},
                "$set": {"last_activity": datetime.now(timezone.utc)},
            },
        )
        return True

    async def is_member_verified(self, user_id: int) -> bool:
        """Check if user is verified (joined channel)"""
        return self.verified_members.find_one({"user_id": user_id}) is not None

    async def mark_member_verified(self, user_id: int) -> bool:
        """Mark user as verified (joined channel)"""
        try:
            self.verified_members.update_one(
                {"user_id": user_id},
                {"$set": {"verified_at": datetime.now(timezone.utc)}},
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
        # Store pending phone numbers for users who haven't joined channel yet
        self.pending_lookups = {}  # {user_id: phone_number}

    @staticmethod
    def validate_phone_number(number: str) -> bool:
        """Validate Indian mobile number (expects clean 10-digit number)"""
        # Validate Indian mobile number (starts with 6-9, exactly 10 digits)
        pattern = r"^[6-9]\d{9}$"
        return bool(re.match(pattern, number))
    
    @staticmethod
    def extract_phone_number(number: str) -> str:
        """Extract clean 10-digit phone number from any format"""
        # Remove all non-digit characters
        digits_only = re.sub(r'\D', '', number.strip())
        
        # Handle +91 prefix - take only last 10 digits
        if digits_only.startswith('91') and len(digits_only) > 10:
            digits_only = digits_only[-10:]
        
        return digits_only

    async def _delete_messages_later(self, bot, chat_id: int, *message_ids: int, delay: int = 10):
        """Delete messages after specified delay"""
        await asyncio.sleep(delay)
        for msg_id in message_ids:
            try:
                await bot.delete_message(chat_id, msg_id)
            except Exception as e:
                # Silently ignore deletion errors (message already deleted, etc.)
                pass

    async def fetch_phone_data(self, phone_number: str):
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

    def format_response(self, data, phone_number: str) -> str:
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
        formatted += "✨ <b>Unlimited searches for everyone!</b>\n"
        formatted += "\n🤖 <b>Buy Unlimited API:</b> @AzApisBot\n"
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

    async def handle_new_members(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle new members joining the group"""
        # Only work in allowed group
        if update.effective_chat.id != config.ALLOWED_GROUP_ID:
            return
        
        # Check if this is a new member message
        if not update.message.new_chat_members:
            return
        
        new_members = update.message.new_chat_members
        for member in new_members:
            # Don't respond to bot joining
            if member.is_bot:
                continue
            
            # Create welcome message with user mention
            welcome_text = (
                f"👋 Welcome {member.mention_html()}!\n\n"
                f"📖 <b>Help Guide</b>\n\n"
                f"<b>Commands:</b>\n"
                f"/start - Welcome message\n"
                f"/help - This help guide\n\n"
                f"<b>How to use:</b>\n"
                f"1. Send any 10-digit Indian mobile number\n"
                f"2. Wait for the bot to fetch intelligence\n"
                f"3. Receive formatted results\n\n"
                f"<b>Example:</b> <code>8929162117</code>\n\n"
                f"<b>Support:</b> @AzTechDeveloper"
            )
            
            sent_msg = await update.message.reply_text(welcome_text, parse_mode="HTML")
            
            # Auto-delete welcome message after 10 seconds
            asyncio.create_task(self._delete_messages_later(
                context.bot,
                update.message.chat.id,
                sent_msg.message_id,
                delay=10
            ))

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline keyboard callbacks"""
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        bot = context.bot

        # Check group
        if query.message.chat.id != config.ALLOWED_GROUP_ID:
            await query.answer("This bot only works in the allowed group!", show_alert=True)
            return

        if query.data == "help":
            await query.edit_message_text(config.HELP_MESSAGE, parse_mode="HTML")

        elif query.data == "verify_join":
            # Check if user joined channel
            is_member = await self.check_channel_membership(user_id, context.bot)
            logger.info(f"Verify join - User {user_id}, is_member: {is_member}, pending_lookups: {self.pending_lookups}")
            
            if is_member:
                await self.db.mark_member_verified(user_id)
                try:
                    await query.message.delete()
                except:
                    pass
                
                # Check if there's a pending phone number lookup
                pending_number = self.pending_lookups.pop(user_id, None)
                logger.info(f"Pending number for user {user_id}: {pending_number}")
                
                if pending_number:
                    # Process the pending phone number
                    await self._process_phone_lookup(
                        user_id,
                        pending_number,
                        context.bot,
                        query.message.chat.id
                    )
                else:
                    # No pending lookup, just show verified message
                    verified_msg = await context.bot.send_message(
                        chat_id=query.message.chat.id,
                        text=config.ALREADY_VERIFIED,
                        parse_mode="HTML"
                    )
                    # Auto-delete verified message after 2 seconds
                    asyncio.create_task(self._delete_messages_later(
                        context.bot,
                        query.message.chat.id,
                        verified_msg.message_id,
                        delay=2
                    ))
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

    async def handle_phone_number(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle phone number messages - UNLIMITED FOR ALL USERS"""
        # Check if message exists (can be None for some update types)
        if not update.message:
            return

        # Only allowed in group
        if update.effective_chat.id != config.ALLOWED_GROUP_ID:
            return

        user_id = update.effective_user.id
        raw_input = update.message.text.strip()
        logger.info(f"Received message from user {user_id}: {raw_input}")

        # Extract clean 10-digit number from any format
        clean_number = self.extract_phone_number(raw_input)
        logger.info(f"Extracted number: {clean_number}")

        # If input contains only alphabets (no valid digits after cleaning), ignore silently
        if not clean_number or not clean_number.isdigit():
            logger.info(f"No valid digits found, ignoring")
            return

        # Validate phone number
        if not self.validate_phone_number(clean_number):
            logger.info(f"Invalid phone number format: {clean_number}")
            return

        logger.info(f"Valid phone number: {clean_number}")

        # Check channel membership
        is_verified = await self.db.is_member_verified(user_id)
        is_member = await self.check_channel_membership(user_id, context.bot)
        logger.info(f"User {user_id} - is_verified: {is_verified}, is_member: {is_member}")

        if not is_member:
            # Store the phone number for later processing after verification
            self.pending_lookups[user_id] = clean_number
            logger.info(f"Stored pending lookup for user {user_id}: {clean_number}")
            
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

        # Track lookup - unlimited for everyone
        await self.db.update_user_lookup(user_id)

        # Send typing indicator
        await update.message.chat.send_action(action="typing")

        # Fetch data using clean 10-digit number
        data = await self.fetch_phone_data(clean_number)

        if not data:
            # Send no results message
            error_msg = await update.message.reply_text(
                config.ERROR_MESSAGES["api_error"],
                parse_mode="HTML"
            )
            # Delete both messages after 10 seconds
            asyncio.create_task(self._delete_messages_later(
                context.bot,
                update.message.chat.id,
                update.message.message_id,
                error_msg.message_id,
                delay=10
            ))
            return

        # Format and send response
        response = self.format_response(data, clean_number)

        # Split message if too long (Telegram limit is 4096 characters)
        MAX_MESSAGE_LENGTH = 4096
        if len(response) <= MAX_MESSAGE_LENGTH:
            await update.message.reply_text(response, parse_mode="HTML")
        else:
            # Split into chunks and send separately
            chunks = []
            current_chunk = ""
            for line in response.split('\n'):
                if len(current_chunk) + len(line) + 1 <= MAX_MESSAGE_LENGTH:
                    current_chunk += line + '\n'
                else:
                    if current_chunk:
                        chunks.append(current_chunk.rstrip())
                    current_chunk = line + '\n'
            if current_chunk:
                chunks.append(current_chunk.rstrip())
            
            # Send each chunk
            for chunk in chunks:
                await update.message.reply_text(chunk, parse_mode="HTML")

    async def _process_phone_lookup(self, user_id: int, phone_number: str, bot, chat_id: int):
        """Process a phone number lookup (used for pending lookups after verification)"""
        logger.info(f"Processing phone lookup for user {user_id}: {phone_number}")
        
        # Track lookup - unlimited for everyone
        await self.db.update_user_lookup(user_id)

        # Send typing indicator
        await bot.send_chat_action(chat_id=chat_id, action="typing")

        # Fetch data using clean 10-digit number
        data = await self.fetch_phone_data(phone_number)
        logger.info(f"API response for {phone_number}: {data}")

        if not data:
            # Send no results message
            error_msg = await bot.send_message(
                chat_id=chat_id,
                text=config.ERROR_MESSAGES["api_error"],
                parse_mode="HTML"
            )
            # Delete error message after 10 seconds
            asyncio.create_task(self._delete_messages_later(
                bot,
                chat_id,
                error_msg.message_id,
                delay=10
            ))
            return

        # Format and send response
        response = self.format_response(data, phone_number)
        logger.info(f"Formatted response length: {len(response)}")

        # Split message if too long (Telegram limit is 4096 characters)
        MAX_MESSAGE_LENGTH = 4096
        if len(response) <= MAX_MESSAGE_LENGTH:
            await bot.send_message(chat_id=chat_id, text=response, parse_mode="HTML")
        else:
            # Split into chunks and send separately
            chunks = []
            current_chunk = ""
            for line in response.split('\n'):
                if len(current_chunk) + len(line) + 1 <= MAX_MESSAGE_LENGTH:
                    current_chunk += line + '\n'
                else:
                    if current_chunk:
                        chunks.append(current_chunk.rstrip())
                    current_chunk = line + '\n'
            if current_chunk:
                chunks.append(current_chunk.rstrip())
            
            # Send each chunk
            for chunk in chunks:
                await bot.send_message(chat_id=chat_id, text=chunk, parse_mode="HTML")


# ==================== MAIN ====================
async def main():
    """Main bot function"""
    # Initialize bot
    bot_instance = PhoneIntelligenceBot()
    
    # Configure application with proper timeout settings
    from telegram.request import HTTPXRequest
    
    # Create request with timeout settings
    request = HTTPXRequest(
        connection_pool_size=8,
        read_timeout=30,
        write_timeout=30,
        connect_timeout=30,
    )
    
    application = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .request(request)
        .build()
    )

    # Add handlers
    application.add_handler(CommandHandler("start", bot_instance.handle_start))
    application.add_handler(CommandHandler("help", bot_instance.handle_help))
    application.add_handler(CallbackQueryHandler(bot_instance.handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot_instance.handle_phone_number))
    application.add_handler(MessageHandler(filters.ALL, bot_instance.handle_new_members))

    # Add error handler to suppress timeout errors
    async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Log errors but suppress timeout errors"""
        from telegram.error import TimedOut, NetworkError
        
        # Suppress timeout and network errors (they happen during shutdown)
        if isinstance(context.error, (TimedOut, NetworkError)):
            return
        
        # Log other errors
        logger.error(f"Exception while handling update: {context.error}")
    
    application.add_error_handler(error_handler)

    # Start bot
    logger.info("Bot is starting...")
    logger.info(f"Allowed Group ID: {config.ALLOWED_GROUP_ID}")
    logger.info(f"Required Channel ID: {config.FORCE_JOIN_CHANNEL_ID}")
    logger.info("All users have unlimited access!")
    
    # Run with graceful shutdown
    try:
        await application.run_polling(drop_pending_updates=True)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down bot...")
    except Exception as e:
        logger.error(f"Bot error: {e}")
    finally:
        # Ensure proper cleanup
        try:
            await application.stop()
            await application.shutdown()
        except Exception as cleanup_error:
            logger.error(f"Cleanup error: {cleanup_error}")


if __name__ == "__main__":
    try:
        # Get the current event loop or create a new one
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        loop.run_until_complete(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped.")
    except Exception as e:
        logger.error(f"Main error: {e}")
    finally:
        # Clean up the event loop
        try:
            loop = asyncio.get_event_loop()
            if not loop.is_closed():
                loop.close()
        except Exception:
            pass
