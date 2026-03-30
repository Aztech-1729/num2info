# bot.py
import asyncio
import logging
import re
from datetime import datetime, timezone

import nest_asyncio
nest_asyncio.apply()

import httpx
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
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.users import GetFullUserRequest
from telethon.errors import UsernameNotOccupiedError, UsernameInvalidError, FloodWaitError
import config

# ==================== LOGGING ====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram.ext._httpxrequest").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.Updater").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("telegram.ext._updater").setLevel(logging.ERROR)
logging.getLogger("telethon").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ==================== GLOBAL TELETHON CLIENT ====================
tg_client: TelegramClient = None


async def init_telethon():
    """Load Telethon session from MongoDB and start client"""
    global tg_client

    mongo_client = MongoClient(config.MONGODB_URI)
    db = mongo_client[config.DATABASE_NAME]
    sessions_col = db["telethon_sessions"]

    record = sessions_col.find_one({"name": "main_session"})
    if not record or not record.get("session_string"):
        logger.error("❌ No Telethon session found in MongoDB. Run session.py first!")
        mongo_client.close()
        return False

    session_string = record["session_string"]
    mongo_client.close()

    tg_client = TelegramClient(
        StringSession(session_string),
        config.TG_API_ID,
        config.TG_API_HASH
    )
    await tg_client.connect()

    if not await tg_client.is_user_authorized():
        logger.error("❌ Telethon session is invalid/expired. Run session.py again!")
        return False

    me = await tg_client.get_me()
    logger.info(f"✅ Telethon ready — logged in as: {me.first_name} (@{me.username})")
    return True


async def _build_user_info(user, full_user_obj, fallback_username: str = "") -> dict:
    """
    Safely build user info dict from Telethon user + full_user objects.
    Guards against None on every field.
    """
    # full_user_obj.about can be None for bots/deleted accounts
    bio = "N/A"
    if full_user_obj is not None and getattr(full_user_obj, "about", None):
        bio = full_user_obj.about

    return {
        "id": user.id,
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "username": user.username or fallback_username or "N/A",
        "bio": bio,
        "verified": getattr(user, "verified", False) or False,
        "premium": getattr(user, "premium", False) or False,
        "bot": getattr(user, "bot", False) or False,
        "scam": getattr(user, "scam", False) or False,
        "fake": getattr(user, "fake", False) or False,
        "restricted": getattr(user, "restricted", False) or False,
        "deleted": getattr(user, "deleted", False) or False,
        "type": "bot" if getattr(user, "bot", False) else "private",
        # store the raw entity so fetch_profile_photo can use it directly
        "_entity": user,
    }


async def resolve_username_full(username: str) -> dict | None:
    """
    Resolve ANY public Telegram username to full profile info using Telethon.
    Works even if user never interacted with the bot or is not in any shared group.
    """
    global tg_client
    if not tg_client:
        logger.warning("Telethon client not available")
        return None

    username = username.lstrip("@").strip()
    try:
        full = await tg_client(GetFullUserRequest(username))

        # Guard: users list must not be empty
        if not full.users:
            logger.warning(f"No users returned for @{username}")
            return None

        user = full.users[0]
        full_user = getattr(full, "full_user", None)
        return await _build_user_info(user, full_user, fallback_username=username)

    except (UsernameNotOccupiedError, UsernameInvalidError):
        logger.warning(f"Username @{username} does not exist")
        return None
    except FloodWaitError as e:
        logger.warning(f"Flood wait {e.seconds}s for username lookup")
        return None
    except Exception as e:
        logger.error(f"Telethon resolve failed for @{username}: {e}")
        return None


async def resolve_userid_full(user_id: int) -> dict | None:
    """
    Resolve a numeric Telegram user ID to full profile info using Telethon.
    """
    global tg_client
    if not tg_client:
        return None
    try:
        full = await tg_client(GetFullUserRequest(user_id))

        # Guard: users list must not be empty
        if not full.users:
            logger.warning(f"No users returned for user_id {user_id}")
            return None

        user = full.users[0]
        full_user = getattr(full, "full_user", None)
        return await _build_user_info(user, full_user)

    except FloodWaitError as e:
        logger.warning(f"Flood wait {e.seconds}s for userid lookup")
        return None
    except Exception as e:
        logger.error(f"Telethon resolve failed for user_id {user_id}: {e}")
        return None


async def fetch_profile_photo(tg_info: dict) -> bytes | None:
    """
    Download the first profile photo of a user as bytes.
    Uses the raw Telethon entity stored in tg_info["_entity"] for reliability.
    Falls back to user_id if entity not available.
    Returns raw bytes or None if no photo or not available.
    """
    global tg_client
    if not tg_client or not tg_info:
        return None
    try:
        import io
        # Use the raw entity object — most reliable way to download profile photo
        entity = tg_info.get("_entity") or tg_info.get("id")
        if not entity:
            return None
        buf = io.BytesIO()
        result = await tg_client.download_profile_photo(entity, file=buf)
        if result:
            buf.seek(0)
            data = buf.read()
            return data if data else None
        return None
    except Exception as e:
        logger.warning(f"Could not download profile photo: {e}")
        return None


# ==================== HOLEHE — EMAIL LOOKUP ====================
# REMOVED: Email lookup functionality has been completely removed

# ==================== INSTALOADER — INSTAGRAM LOOKUP ====================
async def fetch_instagram_profile(username: str) -> dict | None:
    """
    Fetch public Instagram profile using Instagram's public web API.
    No login required for basic public profile info.
    """
    username = username.lstrip("@").strip()
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.instagram.com/",
            "X-IG-App-ID": "936619743392459",
        }

        url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"

        async with httpx.AsyncClient(
            timeout=15,
            headers=headers,
            follow_redirects=True
        ) as client:
            response = await client.get(url)

            if response.status_code == 404:
                logger.warning(f"Instagram profile @{username} not found (404)")
                return None

            if response.status_code != 200:
                logger.error(f"Instagram API returned {response.status_code} for @{username}")
                return None

            data = response.json()
            user = data.get("data", {}).get("user")
            if not user:
                logger.warning(f"No user data in Instagram response for @{username}")
                return None

            return {
                "username": user.get("username", username),
                "full_name": user.get("full_name") or "N/A",
                "biography": user.get("biography") or "N/A",
                "followers": user.get("edge_followed_by", {}).get("count", 0),
                "followees": user.get("edge_follow", {}).get("count", 0),
                "posts": user.get("edge_owner_to_timeline_media", {}).get("count", 0),
                "is_verified": user.get("is_verified", False),
                "is_private": user.get("is_private", False),
                "is_business": user.get("is_business_account", False),
                "external_url": user.get("external_url") or "N/A",
                "profile_pic_url": user.get("profile_pic_url_hd") or user.get("profile_pic_url", ""),
                "userid": user.get("id", "N/A"),
                "category": user.get("category_name") or "N/A",
            }

    except httpx.TimeoutException:
        logger.error(f"Instagram request timed out for @{username}")
        return None
    except Exception as e:
        logger.error(f"Instagram fetch error for @{username}: {e}")
        return None


# ==================== DATABASE ====================
class Database:
    def __init__(self):
        try:
            self.client = MongoClient(config.MONGODB_URI)
            self.db = self.client[config.DATABASE_NAME]
            self.users = self.db.users
            self.verified_members = self.db.verified_members
            self.daily_limits = self.db.daily_limits
            self._create_indexes()
            logger.info("MongoDB connected successfully")
        except Exception as e:
            logger.error(f"MongoDB connection failed: {e}")
            raise

    def _create_indexes(self):
        self.users.create_index("user_id", unique=True)
        self.verified_members.create_index("user_id", unique=True)
        self.daily_limits.create_index([("user_id", 1), ("date", 1)], unique=True)

    async def get_user(self, user_id: int):
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
        self.users.update_one(
            {"user_id": user_id},
            {
                "$inc": {"total_lookups": 1},
                "$set": {"last_activity": datetime.now(timezone.utc)},
            },
        )
        return True

    async def is_member_verified(self, user_id: int) -> bool:
        return self.verified_members.find_one({"user_id": user_id}) is not None

    async def mark_member_verified(self, user_id: int) -> bool:
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

    async def get_daily_usage(self, user_id: int) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        record = self.daily_limits.find_one({"user_id": user_id, "date": today})
        return record.get("count", 0) if record else 0

    async def increment_daily_usage(self, user_id: int) -> bool:
        today = datetime.now(timezone.utc).date().isoformat()
        try:
            self.daily_limits.update_one(
                {"user_id": user_id, "date": today},
                {"$inc": {"count": 1}, "$setOnInsert": {"date": today}},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Increment daily usage failed: {e}")
            return False

    async def can_do_username_lookup(self, user_id: int) -> tuple[bool, int]:
        usage = await self.get_daily_usage(user_id)
        return usage < config.USERNAME_LOOKUP_DAILY_LIMIT, config.USERNAME_LOOKUP_DAILY_LIMIT - usage


# ==================== BOT CLASS ====================
class PhoneIntelligenceBot:
    def __init__(self):
        self.db = Database()
        self.api_endpoint = config.API_ENDPOINT
        self.api_key = config.API_KEY
        self.username_api_endpoint = config.USERNAME_API_ENDPOINT
        self.username_api_key = config.USERNAME_API_KEY
        self.pending_lookups = {}

    @staticmethod
    def validate_phone_number(number: str) -> bool:
        pattern = r"^[6-9]\d{9}$"
        return bool(re.match(pattern, number))

    @staticmethod
    def extract_phone_number(number: str) -> str:
        digits_only = re.sub(r'\D', '', number.strip())
        if digits_only.startswith('91') and len(digits_only) > 10:
            digits_only = digits_only[-10:]
        return digits_only

    @staticmethod
    def extract_input_type(text: str) -> tuple[str, str] | tuple[None, None]:
        """Detect what the user sent: instagram, tg username, userid"""
        text = text.strip()

        # Instagram link e.g. instagram.com/username
        ig_link = re.search(r'instagram\.com/([\w.]+)', text)
        if ig_link:
            return 'instagram', ig_link.group(1)

        # Telegram username @handle
        username_match = re.search(r'@([a-zA-Z][a-zA-Z0-9_]{4,31})', text)
        if username_match:
            return 'username', username_match.group(1)

        # Numeric Telegram user ID
        userid_match = re.search(r'\b(\d{8,15})\b', text)
        if userid_match:
            potential_id = userid_match.group(1)
            if len(potential_id) == 10 and potential_id[0] in '6789':
                return None, None
            return 'userid', potential_id

        return None, None

    @staticmethod
    def extract_username_or_userid(text: str) -> tuple[str, str] | tuple[None, None]:
        text = text.strip()
        username_match = re.search(r'@([a-zA-Z][a-zA-Z0-9_]{4,31})', text)
        if username_match:
            return 'username', username_match.group(1)
        userid_match = re.search(r'\b(\d{8,15})\b', text)
        if userid_match:
            potential_id = userid_match.group(1)
            if len(potential_id) == 10 and potential_id[0] in '6789':
                return None, None
            return 'userid', potential_id
        return None, None

    async def _delete_messages_later(self, bot, chat_id: int, *message_ids: int, delay: int = 10):
        await asyncio.sleep(delay)
        for msg_id in message_ids:
            try:
                await bot.delete_message(chat_id, msg_id)
            except Exception:
                pass

    async def fetch_phone_data(self, phone_number: str):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                params = {"key": self.api_key, "num": phone_number}
                response = await client.get(self.api_endpoint, params=params)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("success") and data.get("result"):
                        return data
                return None
        except Exception as e:
            logger.error(f"API fetch error: {e}")
            return None

    async def fetch_username_phone_data(self, user_id: str):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                params = {"key": self.username_api_key, "q": user_id}
                response = await client.get(self.username_api_endpoint, params=params)
                if response.status_code == 200:
                    return response.json()
                return None
        except Exception as e:
            logger.error(f"Username API fetch error: {e}")
            return None

    def format_response(self, data, phone_number: str) -> tuple[str, list[str]]:
        """Returns (formatted_text, list_of_emails_found)"""
        results = data.get("result", [])
        if not results:
            return config.ERROR_MESSAGES["no_data"], []

        formatted = "<b>🔍 Phone Intelligence Report</b>\n"
        formatted += f"<b>📱 Number:</b> <code>{phone_number}</code>\n"
        formatted += "=" * 35 + "\n\n"
        emails_found = []

        for idx, result in enumerate(results, 1):
            if len(results) > 1:
                formatted += f"<b>📌 Result {idx}</b>\n"
                formatted += "─" * 25 + "\n"

            if result.get("name"):
                name = str(result['name']).replace('<', '').replace('>', '')
                formatted += f"👤 <b>Name:</b> {name}\n"
            if result.get("father_name"):
                fname = str(result['father_name']).replace('<', '').replace('>', '')
                formatted += f"👨 <b>Father/Husband:</b> {fname}\n"
            if result.get("address"):
                address = str(result['address']).replace('\n', ' ').replace('<', '').replace('>', '')
                formatted += f"📍 <b>Address:</b> {address}\n"
            if result.get("alt_mobile"):
                alt = str(result['alt_mobile']).replace('<', '').replace('>', '')
                formatted += f"📞 <b>Alt Mobile:</b> <code>{alt}</code>\n"
            if result.get("circle"):
                circle = str(result['circle']).replace('<', '').replace('>', '')
                formatted += f"📡 <b>Network:</b> {circle}\n"
            if result.get("email"):
                email = str(result['email']).replace('<', '').replace('>', '').strip()
                formatted += f"✉️ <b>Email:</b> {email}\n"
            if result.get("id_number"):
                id_num = str(result['id_number']).replace('<', '').replace('>', '')
                formatted += f"🆔 <b>ID:</b> <code>{id_num}</code>\n"
            formatted += "\n"

        formatted += "=" * 35 + "\n"
        formatted += f"🔮 <b>Powered by:</b> @AzTechDeveloper\n"
        formatted += "✨ <b>Unlimited searches for everyone!</b>\n"
        formatted += "\n🤖 <b>Buy Unlimited API:</b> @AzApisBot\n"
        return formatted, emails_found

    def format_tg_profile_block(self, tg_info: dict) -> str:
        """Format Telegram profile info into a beautiful block"""
        if not tg_info:
            return ""
        full_name = f"{tg_info.get('first_name', '')} {tg_info.get('last_name', '')}".strip() or "N/A"
        username = tg_info.get('username', 'N/A')
        username_display = f"@{username}" if username and username != "N/A" else "N/A"

        block = (
            f"👤 <b>Telegram Profile</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 <b>User ID:</b> <code>{tg_info['id']}</code>\n"
            f"📛 <b>Name:</b> {full_name}\n"
            f"🔖 <b>Username:</b> {username_display}\n"
            f"📝 <b>Bio:</b> {tg_info.get('bio', 'N/A')}\n"
            f"✅ <b>Verified:</b> {'Yes ✅' if tg_info.get('verified') else 'No'}\n"
            f"💎 <b>Premium:</b> {'Yes 💎' if tg_info.get('premium') else 'No'}\n"
            f"🤖 <b>Bot:</b> {'Yes' if tg_info.get('bot') else 'No'}\n"
            f"⚠️ <b>Scam:</b> {'Yes ⚠️' if tg_info.get('scam') else 'No'}\n"
            f"🚫 <b>Fake:</b> {'Yes 🚫' if tg_info.get('fake') else 'No'}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
        )
        return block

    def format_username_response(self, data: dict, requested_by: str, original_input: str, tg_info: dict = None, remaining: int = 0, is_admin: bool = False) -> str:
        """Format the username API response — includes Telegram profile block if available"""
        # Guard: data could be None or missing the key entirely
        phone_info = {}
        if data and isinstance(data, dict):
            phone_info = data.get("phone_info_from_id") or {}

        # Search counter line
        if is_admin:
            search_line = "🔍 <b>Searches remaining:</b> ♾️ Unlimited (Admin)\n\n"
        else:
            remaining_after = max(remaining - 1, 0)
            search_line = f"🔍 <b>Searches remaining:</b> {remaining_after}/{config.USERNAME_LOOKUP_DAILY_LIMIT}\n\n"

        if not phone_info.get("success"):
            if tg_info:
                response = f"👤 <b>Requested by:</b> {requested_by}\n"
                response += search_line
                response += self.format_tg_profile_block(tg_info)
                response += "\n🔍 <b>No phone number linked to this account.</b>\n"
                response += "=" * 35 + "\n"
                if is_admin:
                    response += "🔮 <b>Powered by:</b> @AzTechDeveloper | Admin ♾️ Unlimited\n"
                else:
                    response += "🔮 <b>Powered by:</b> @AzTechDeveloper\n"
                return response
            return config.ERROR_MESSAGES["no_username_data"]

        user_id = data.get("user_id", original_input)
        country = phone_info.get("country", "Unknown")
        country_code = phone_info.get("country_code", "Unknown")
        phone_number = phone_info.get("number", "Unknown")

        formatted = f"👤 <b>Requested by:</b> {requested_by}\n"
        formatted += search_line

        # Add Telegram profile block first if available
        if tg_info:
            formatted += self.format_tg_profile_block(tg_info)
            formatted += "\n"

        # Phone info section
        formatted += "📞 <b>Phone Info</b>\n"
        formatted += f"├ <b>User ID:</b> <code>{user_id}</code>\n"
        formatted += f"├ <b>Country:</b> {country}\n"
        formatted += f"├ <b>Country Code:</b> {country_code}\n"
        formatted += f"└ <b>Phone Number:</b> <code>{phone_number}</code>\n\n"
        formatted += "=" * 35 + "\n"
        if is_admin:
            formatted += "🔮 <b>Powered by:</b> @AzTechDeveloper | Admin ♾️ Unlimited\n"
        else:
            formatted += "🔮 <b>Powered by:</b> @AzTechDeveloper\n"

        return formatted

    async def check_channel_membership(self, user_id: int, bot_instance) -> bool:
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
        user = update.effective_user
        await self.db.get_user(user.id)

        if update.effective_chat.id != config.ALLOWED_GROUP_ID:
            await update.message.reply_text(
                config.NOT_IN_GROUP.format(group_link=config.ALLOWED_GROUP_LINK),
                parse_mode="HTML"
            )
            return

        keyboard = [[InlineKeyboardButton("❓ Help", callback_data="help")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(config.WELCOME_MESSAGE, parse_mode="HTML", reply_markup=reply_markup)

    async def handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id != config.ALLOWED_GROUP_ID:
            return
        await update.message.reply_text(config.HELP_MESSAGE, parse_mode="HTML")

    async def handle_new_members(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id != config.ALLOWED_GROUP_ID:
            return
        if not update.message.new_chat_members:
            return

        new_members = update.message.new_chat_members
        for member in new_members:
            if member.is_bot:
                continue

            welcome_text = (
                f"👋 Welcome {member.mention_html()}!\n\n"
                f"📖 <b>Help Guide</b>\n\n"
                f"<b>Commands:</b>\n"
                f"/start - Welcome message\n"
                f"/help - This help guide\n"
                f"/ig @username - Instagram profile lookup\n\n"
                f"<b>How to use:</b>\n"
                f"📱 <b>Phone Lookup:</b> Send any 10-digit Indian mobile number\n"
                f"👤 <b>Username Lookup:</b> Send @username or user ID (3/day limit)\n"
                f"📸 <b>Instagram Lookup:</b> Send @username or use /ig @username\n\n"
                f"<b>Examples:</b>\n"
                f"• Phone: <code>8929162117</code>\n"
                f"• Username: <code>@telegram</code>\n"
                f"• User ID: <code>1234567890</code>\n"
                f"• Instagram: <code>@instagram</code>\n\n"
                f"<b>Support:</b> @AzTechDeveloper"
            )

            sent_msg = await update.message.reply_text(welcome_text, parse_mode="HTML")
            asyncio.create_task(self._delete_messages_later(
                context.bot,
                update.message.chat.id,
                sent_msg.message_id,
                delay=60
            ))

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        if query.data == "help":
            await query.message.reply_text(config.HELP_MESSAGE, parse_mode="HTML")

        elif query.data == "verify_join":
            user_id = query.from_user.id
            is_member = await self.check_channel_membership(user_id, context.bot)

            if is_member:
                await self.db.mark_member_verified(user_id)
                try:
                    await query.message.delete()
                except Exception:
                    pass

                pending = self.pending_lookups.pop(user_id, None)
                if pending and pending.startswith("__tg__"):
                    # Pending username/userid lookup
                    _, payload = pending.split("__tg__", 1)
                    p_type, p_value = payload.split(":", 1)
                    user_obj = query.from_user
                    display_name = user_obj.first_name if user_obj.first_name else f"User_{user_id}"
                    requested_by = f'<a href="tg://user?id={user_id}">{display_name}</a>'
                    is_admin = (user_id == config.ADMIN_USER_ID)
                    _, remaining = await self.db.can_do_username_lookup(user_id)

                    await context.bot.send_chat_action(chat_id=query.message.chat.id, action="typing")

                    tg_info = None
                    target_user_id = p_value
                    if p_type == 'username':
                        tg_info = await resolve_username_full(p_value)
                        if tg_info:
                            target_user_id = str(tg_info["id"])
                    elif p_type == 'userid':
                        try:
                            tg_info = await resolve_userid_full(int(p_value))
                        except ValueError:
                            pass

                    data = await self.fetch_username_phone_data(target_user_id)

                    if not data:
                        if tg_info:
                            if not is_admin:
                                await self.db.increment_daily_usage(user_id)
                            remaining_after = max(remaining - 1, 0)
                            search_line = "🔍 <b>Searches remaining:</b> ♾️ Unlimited (Admin)\n\n" if is_admin else f"🔍 <b>Searches remaining:</b> {remaining_after}/{config.USERNAME_LOOKUP_DAILY_LIMIT}\n\n"
                            response = f"👤 <b>Requested by:</b> {requested_by}\n"
                            response += search_line
                            response += self.format_tg_profile_block(tg_info)
                            response += "\n🔍 <b>No phone number data available from API.</b>\n"
                            response += "=" * 35 + "\n"
                            response += "🔮 <b>Powered by:</b> @AzTechDeveloper | Admin ♾️ Unlimited\n" if is_admin else "🔮 <b>Powered by:</b> @AzTechDeveloper\n"
                            await self._send_lookup_response(
                                bot=context.bot,
                                chat_id=query.message.chat.id,
                                text=response,
                                tg_info=tg_info
                            )
                        else:
                            await context.bot.send_message(chat_id=query.message.chat.id, text=config.ERROR_MESSAGES["api_error"], parse_mode="HTML")
                    else:
                        phone_info = data.get("phone_info_from_id", {})
                        if not phone_info.get("success") and not tg_info:
                            await context.bot.send_message(chat_id=query.message.chat.id, text=config.ERROR_MESSAGES["no_username_data"], parse_mode="HTML")
                        else:
                            if not is_admin:
                                await self.db.increment_daily_usage(user_id)
                            response = self.format_username_response(
                                data, requested_by, p_value,
                                tg_info=tg_info, remaining=remaining, is_admin=is_admin
                            )
                            await self._send_lookup_response(
                                bot=context.bot,
                                chat_id=query.message.chat.id,
                                text=response,
                                tg_info=tg_info
                            )

                elif pending and pending.startswith("__ig__"):
                    # Pending Instagram lookup
                    ig_username = pending.split("__ig__", 1)[1]
                    user_obj = query.from_user
                    display_name = user_obj.first_name if user_obj.first_name else f"User_{user_id}"
                    requested_by = f'<a href="tg://user?id={user_id}">{display_name}</a>'
                    await context.bot.send_chat_action(chat_id=query.message.chat.id, action="typing")
                    data = await fetch_instagram_profile(ig_username)
                    if data:
                        response = self.format_instagram_response(data, requested_by)
                        try:
                            import httpx as _httpx, io
                            async with _httpx.AsyncClient(timeout=10) as client:
                                pic_resp = await client.get(data["profile_pic_url"])
                                if pic_resp.status_code == 200 and len(response) <= 1024:
                                    await context.bot.send_photo(chat_id=query.message.chat.id, photo=io.BytesIO(pic_resp.content), caption=response, parse_mode="HTML")
                                elif pic_resp.status_code == 200:
                                    await context.bot.send_photo(chat_id=query.message.chat.id, photo=io.BytesIO(pic_resp.content), caption="📸 <b>Instagram Profile Photo</b>", parse_mode="HTML")
                                    await context.bot.send_message(chat_id=query.message.chat.id, text=response, parse_mode="HTML")
                                else:
                                    await context.bot.send_message(chat_id=query.message.chat.id, text=response, parse_mode="HTML")
                        except Exception:
                            await context.bot.send_message(chat_id=query.message.chat.id, text=response, parse_mode="HTML")
                    else:
                        await context.bot.send_message(chat_id=query.message.chat.id, text=f"❌ Instagram profile not found.", parse_mode="HTML")

                elif pending:
                    # Pending phone number lookup
                    await self._process_phone_lookup(
                        user_id, pending, context.bot, query.message.chat.id
                    )
                else:
                    verified_msg = await context.bot.send_message(
                        chat_id=query.message.chat.id,
                        text=config.ALREADY_VERIFIED,
                        parse_mode="HTML"
                    )
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
                except Exception:
                    pass

    async def handle_phone_number(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return
        if update.effective_chat.id != config.ALLOWED_GROUP_ID:
            return

        user_id = update.effective_user.id
        raw_input = update.message.text.strip()
        logger.info(f"Received message from user {user_id}: {raw_input}")

        # Detect input type — instagram, tg username, tg userid, phone
        input_type, input_value = self.extract_input_type(raw_input)

        if input_type == 'instagram':
            logger.info(f"Detected Instagram: {input_value}")
            await self.handle_instagram_lookup(update, context, input_value)
            return

        if input_type in ('username', 'userid'):
            logger.info(f"Detected {input_type}: {input_value}")
            await self.handle_username_lookup(update, context, input_type, input_value)
            return

        # Phone number flow
        clean_number = self.extract_phone_number(raw_input)
        if not clean_number or not clean_number.isdigit():
            return
        if not self.validate_phone_number(clean_number):
            return

        is_member = await self.check_channel_membership(user_id, context.bot)
        if not is_member:
            self.pending_lookups[user_id] = clean_number
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

        is_verified = await self.db.is_member_verified(user_id)
        if not is_verified:
            await self.db.mark_member_verified(user_id)

        await self.db.update_user_lookup(user_id)
        await update.message.chat.send_action(action="typing")

        data = await self.fetch_phone_data(clean_number)
        if not data:
            error_msg = await update.message.reply_text(
                config.ERROR_MESSAGES["api_error"],
                parse_mode="HTML"
            )
            asyncio.create_task(self._delete_messages_later(
                context.bot,
                update.message.chat.id,
                update.message.message_id,
                error_msg.message_id,
                delay=10
            ))
            return

        response, emails_found = self.format_response(data, clean_number)
        MAX_MESSAGE_LENGTH = 4096

        reply_markup = None

        if len(response) <= MAX_MESSAGE_LENGTH:
            await update.message.reply_text(response, parse_mode="HTML", reply_markup=reply_markup)
        else:
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
            for i, chunk in enumerate(chunks):
                if i == len(chunks) - 1:
                    await update.message.reply_text(chunk, parse_mode="HTML", reply_markup=reply_markup)
                else:
                    await update.message.reply_text(chunk, parse_mode="HTML")

    async def handle_username_lookup(self, update: Update, context: ContextTypes.DEFAULT_TYPE, input_type: str, input_value: str):
        """Handle username or user ID lookup — uses Telethon for full profile"""
        user_id = update.effective_user.id
        user = update.effective_user
        display_name = user.first_name if user.first_name else f"User_{user_id}"
        # Clickable name — tapping opens their Telegram profile
        requested_by = f'<a href="tg://user?id={user_id}">{display_name}</a>'

        logger.info(f"Handling {input_type} lookup for user {user_id}: {input_value}")

        # Block protected users
        if input_type == 'username' and input_value.lower() in config.PROTECTED_USERNAMES:
            return
        if input_type == 'userid' and input_value in config.PROTECTED_USER_IDS:
            return

        # Admin gets unlimited searches, normal users have daily limit
        is_admin = (user_id == config.ADMIN_USER_ID)

        if is_admin:
            remaining = config.USERNAME_LOOKUP_DAILY_LIMIT  # shown as unlimited in output
        else:
            can_lookup, remaining = await self.db.can_do_username_lookup(user_id)
            if not can_lookup:
                await update.message.reply_text(
                    config.ERROR_MESSAGES["daily_limit_exceeded"].format(
                        limit=config.USERNAME_LOOKUP_DAILY_LIMIT
                    ),
                    parse_mode="HTML"
                )
                return

        # Check channel membership
        is_member = await self.check_channel_membership(user_id, context.bot)
        if not is_member:
            # Save username/userid as pending so it processes after verify
            self.pending_lookups[user_id] = f"__tg__{input_type}:{input_value}"
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

        await update.message.chat.send_action(action="typing")

        # ── Resolve via Telethon ──────────────────────────────────────────
        tg_info = None
        target_user_id = input_value

        if input_type == 'username':
            logger.info(f"Resolving username @{input_value} via Telethon...")
            tg_info = await resolve_username_full(input_value)
            if tg_info:
                target_user_id = str(tg_info["id"])
                logger.info(f"Resolved @{input_value} → ID {target_user_id}")
            else:
                logger.info(f"Telethon could not resolve @{input_value}, trying API directly")

        elif input_type == 'userid':
            logger.info(f"Resolving user ID {input_value} via Telethon...")
            try:
                tg_info = await resolve_userid_full(int(input_value))
            except ValueError:
                pass
            if tg_info:
                logger.info(f"Resolved user ID {input_value} → @{tg_info.get('username')}")
        # ─────────────────────────────────────────────────────────────────

        # Fetch phone data from your API
        data = await self.fetch_username_phone_data(target_user_id)

        if not data:
            # No API data — but still show Telegram profile if we have it
            if tg_info:
                if not is_admin:
                    await self.db.increment_daily_usage(user_id)
                remaining_after = max(remaining - 1, 0)
                search_line = "🔍 <b>Searches remaining:</b> ♾️ Unlimited (Admin)\n\n" if is_admin else f"🔍 <b>Searches remaining:</b> {remaining_after}/{config.USERNAME_LOOKUP_DAILY_LIMIT}\n\n"
                response = f"👤 <b>Requested by:</b> {requested_by}\n"
                response += search_line
                response += self.format_tg_profile_block(tg_info)
                response += "\n🔍 <b>No phone number data available from API.</b>\n"
                response += "=" * 35 + "\n"
                response += "🔮 <b>Powered by:</b> @AzTechDeveloper | Admin ♾️ Unlimited\n" if is_admin else "🔮 <b>Powered by:</b> @AzTechDeveloper\n"
                await self._send_lookup_response(
                    bot=context.bot,
                    chat_id=update.message.chat.id,
                    text=response,
                    tg_info=tg_info,
                    reply_to=update.message.message_id
                )
            else:
                await update.message.reply_text(
                    config.ERROR_MESSAGES["api_error"],
                    parse_mode="HTML"
                )
            return

        # Check phone data success
        phone_info = data.get("phone_info_from_id", {})
        if not phone_info.get("success") and not tg_info:
            await update.message.reply_text(
                config.ERROR_MESSAGES["no_username_data"],
                parse_mode="HTML"
            )
            return

        # Increment usage (skip for admin)
        if not is_admin:
            await self.db.increment_daily_usage(user_id)

        # Format and send — pass tg_info, remaining, is_admin
        response = self.format_username_response(
            data, requested_by, input_value,
            tg_info=tg_info, remaining=remaining, is_admin=is_admin
        )
        await self._send_lookup_response(
            bot=context.bot,
            chat_id=update.message.chat.id,
            text=response,
            tg_info=tg_info,
            reply_to=update.message.message_id
        )

    async def _send_lookup_response(self, bot, chat_id: int, text: str, tg_info: dict | None = None, reply_to: int | None = None):
        """
        Send lookup result. If profile photo available → send as photo with caption.
        Falls back to plain text message if no photo or caption too long.
        Caption limit in Telegram is 1024 chars.
        """
        photo_bytes = None
        if tg_info:
            photo_bytes = await fetch_profile_photo(tg_info)

        import io
        MAX_CAPTION = 1024

        if photo_bytes and len(text) <= MAX_CAPTION:
            # Send photo with full text as caption
            await bot.send_photo(
                chat_id=chat_id,
                photo=io.BytesIO(photo_bytes),
                caption=text,
                parse_mode="HTML",
                reply_to_message_id=reply_to
            )
        elif photo_bytes:
            # Text too long for caption — send photo first, then text separately
            await bot.send_photo(
                chat_id=chat_id,
                photo=io.BytesIO(photo_bytes),
                caption="🖼 <b>Profile Photo</b>",
                parse_mode="HTML",
                reply_to_message_id=reply_to
            )
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        else:
            # No photo — plain text
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                reply_to_message_id=reply_to
            )

    def format_instagram_response(self, data: dict, requested_by: str) -> str:
        """Format Instagram profile lookup result"""
        followers = f"{data['followers']:,}"
        following = f"{data['followees']:,}"
        posts = f"{data['posts']:,}"

        formatted = f"👤 <b>Requested by:</b> {requested_by}\n\n"
        formatted += f"📸 <b>Instagram Profile</b>\n"
        formatted += f"━━━━━━━━━━━━━━━━━━━━\n"
        ig_url = f"https://instagram.com/{data['username']}"
        formatted += f'🔖 <b>Username:</b> <a href="{ig_url}">@{data["username"]}</a>\n'
        formatted += f"📛 <b>Name:</b> {data['full_name']}\n"
        formatted += f"🆔 <b>User ID:</b> <code>{data['userid']}</code>\n"
        formatted += f"📝 <b>Bio:</b> {data['biography']}\n"
        formatted += f"🔗 <b>URL:</b> {data['external_url']}\n"
        formatted += f"━━━━━━━━━━━━━━━━━━━━\n"
        formatted += f"👥 <b>Followers:</b> {followers}\n"
        formatted += f"➡️ <b>Following:</b> {following}\n"
        formatted += f"📦 <b>Posts:</b> {posts}\n"
        formatted += f"━━━━━━━━━━━━━━━━━━━━\n"
        formatted += f"✅ <b>Verified:</b> {'Yes ✅' if data['is_verified'] else 'No'}\n"
        formatted += f"🔒 <b>Private:</b> {'Yes 🔒' if data['is_private'] else 'No'}\n"
        formatted += f"💼 <b>Business:</b> {'Yes' if data['is_business'] else 'No'}\n"
        formatted += f"🏷️ <b>Category:</b> {data.get('category', 'N/A')}\n"
        formatted += f"━━━━━━━━━━━━━━━━━━━━\n"
        formatted += f"🔮 <b>Powered by:</b> @AzTechDeveloper\n"
        return formatted


    async def handle_ig_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/ig @username — Instagram profile lookup command"""
        if not update.message:
            return
        if update.effective_chat.id != config.ALLOWED_GROUP_ID:
            return

        args = context.args
        if not args:
            await update.message.reply_text(
                "❌ Usage: <code>/ig @username</code> or <code>/ig username</code>",
                parse_mode="HTML"
            )
            return

        username = args[0].lstrip("@").strip()
        if not username:
            await update.message.reply_text(
                "❌ Please provide a valid Instagram username.",
                parse_mode="HTML"
            )
            return

        await self.handle_instagram_lookup(update, context, username)

    async def handle_instagram_lookup(self, update: Update, context: ContextTypes.DEFAULT_TYPE, username: str):
        """Handle Instagram profile lookup using instaloader"""
        user_id = update.effective_user.id
        user = update.effective_user
        display_name = user.first_name if user.first_name else f"User_{user_id}"
        requested_by = f'<a href="tg://user?id={user_id}">{display_name}</a>'

        # Check channel membership
        is_member = await self.check_channel_membership(user_id, context.bot)
        if not is_member:
            self.pending_lookups[user_id] = f"__ig__{username}"
            keyboard = [
                [InlineKeyboardButton(config.BTN_JOIN_CHANNEL, url=config.FORCE_JOIN_CHANNEL_LINK)],
                [InlineKeyboardButton(config.BTN_VERIFY_JOIN, callback_data="verify_join")]
            ]
            await update.message.reply_text(
                config.FORCE_JOIN_MESSAGE.format(channel_link=config.FORCE_JOIN_CHANNEL_LINK),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        await update.message.chat.send_action(action="typing")

        data = await fetch_instagram_profile(username)
        if not data:
            await update.message.reply_text(
                f"❌ Instagram profile <code>@{username}</code> not found or is private.",
                parse_mode="HTML"
            )
            return

        response = self.format_instagram_response(data, requested_by)

        # Try to send profile pic from Instagram
        try:
            import httpx as _httpx
            import io
            async with _httpx.AsyncClient(timeout=10) as client:
                pic_resp = await client.get(data["profile_pic_url"])
                if pic_resp.status_code == 200 and len(response) <= 1024:
                    await update.message.reply_photo(
                        photo=io.BytesIO(pic_resp.content),
                        caption=response,
                        parse_mode="HTML"
                    )
                elif pic_resp.status_code == 200:
                    await update.message.reply_photo(
                        photo=io.BytesIO(pic_resp.content),
                        caption="📸 <b>Instagram Profile Photo</b>",
                        parse_mode="HTML"
                    )
                    await update.message.reply_text(response, parse_mode="HTML")
                else:
                    await update.message.reply_text(response, parse_mode="HTML")
        except Exception:
            await update.message.reply_text(response, parse_mode="HTML")

    async def _process_phone_lookup(self, user_id: int, phone_number: str, bot, chat_id: int):
        await self.db.update_user_lookup(user_id)
        await bot.send_chat_action(chat_id=chat_id, action="typing")

        data = await self.fetch_phone_data(phone_number)
        if not data:
            error_msg = await bot.send_message(
                chat_id=chat_id,
                text=config.ERROR_MESSAGES["api_error"],
                parse_mode="HTML"
            )
            asyncio.create_task(self._delete_messages_later(bot, chat_id, error_msg.message_id, delay=10))
            return

        response, emails_found = self.format_response(data, phone_number)
        MAX_MESSAGE_LENGTH = 4096

        reply_markup = None

        if len(response) <= MAX_MESSAGE_LENGTH:
            await bot.send_message(chat_id=chat_id, text=response, parse_mode="HTML", reply_markup=reply_markup)
        else:
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
            for i, chunk in enumerate(chunks):
                if i == len(chunks) - 1:
                    await bot.send_message(chat_id=chat_id, text=chunk, parse_mode="HTML", reply_markup=reply_markup)
                else:
                    await bot.send_message(chat_id=chat_id, text=chunk, parse_mode="HTML")



# ==================== MAIN ====================
async def main():
    # Start Telethon session from MongoDB
    telethon_ok = await init_telethon()
    if not telethon_ok:
        logger.warning("⚠️  Telethon not available — username resolution will be limited to bot.get_chat()")

    bot_instance = PhoneIntelligenceBot()

    from telegram.request import HTTPXRequest
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

    application.add_handler(CommandHandler("start", bot_instance.handle_start))
    application.add_handler(CommandHandler("help", bot_instance.handle_help))
    application.add_handler(CommandHandler("ig", bot_instance.handle_ig_command))
    application.add_handler(CallbackQueryHandler(bot_instance.handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot_instance.handle_phone_number))
    application.add_handler(MessageHandler(filters.ALL, bot_instance.handle_new_members))

    async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        from telegram.error import TimedOut, NetworkError
        if isinstance(context.error, (TimedOut, NetworkError)):
            return
        logger.error(f"Exception while handling update: {context.error}")

    application.add_error_handler(error_handler)

    logger.info("Bot is starting...")
    logger.info(f"Allowed Group ID: {config.ALLOWED_GROUP_ID}")
    logger.info(f"Required Channel ID: {config.FORCE_JOIN_CHANNEL_ID}")

    try:
        await application.run_polling(drop_pending_updates=True)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down bot...")
    except Exception as e:
        logger.error(f"Bot error: {e}")
    finally:
        if tg_client:
            await tg_client.disconnect()
        try:
            await application.stop()
            await application.shutdown()
        except Exception as cleanup_error:
            logger.error(f"Cleanup error: {cleanup_error}")


if __name__ == "__main__":
    try:
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
        try:
            loop = asyncio.get_event_loop()
            if not loop.is_closed():
                loop.close()
        except Exception:
            pass