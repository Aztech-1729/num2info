# session.py
# Run this file ONCE to login and save your Telethon session to MongoDB
# After that, bot.py will automatically load the session from MongoDB

import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from pymongo import MongoClient
import config

async def create_and_save_session():
    print("=" * 50)
    print("  Telethon Session Creator")
    print("=" * 50)
    print()
    print("This will login to your Telegram account and")
    print("save the session to MongoDB for the bot to use.")
    print()

    # Connect to MongoDB
    mongo_client = MongoClient(config.MONGODB_URI)
    db = mongo_client[config.DATABASE_NAME]
    sessions_col = db["telethon_sessions"]

    # Check if session already exists
    existing = sessions_col.find_one({"name": "main_session"})
    if existing:
        print("⚠️  A session already exists in MongoDB.")
        overwrite = input("Do you want to overwrite it? (yes/no): ").strip().lower()
        if overwrite != "yes":
            print("❌ Cancelled. Existing session kept.")
            return

    # Create Telethon client with StringSession (stores as string, easy for MongoDB)
    client = TelegramClient(StringSession(), config.TG_API_ID, config.TG_API_HASH)

    print("📱 Starting login process...")
    print("You will receive an OTP on your Telegram app.\n")

    await client.start()  # Prompts for phone number and OTP automatically

    # Get session string
    session_string = client.session.save()

    # Get logged-in account info
    me = await client.get_me()
    print(f"\n✅ Logged in as: {me.first_name} (@{me.username}) | ID: {me.id}")

    # Save to MongoDB
    sessions_col.update_one(
        {"name": "main_session"},
        {
            "$set": {
                "name": "main_session",
                "session_string": session_string,
                "account_id": me.id,
                "account_name": me.first_name,
                "account_username": me.username,
            }
        },
        upsert=True
    )

    print("\n✅ Session saved to MongoDB successfully!")
    print("✅ You can now run bot.py — it will use this session automatically.")
    print()

    await client.disconnect()
    mongo_client.close()


if __name__ == "__main__":
    asyncio.run(create_and_save_session())
