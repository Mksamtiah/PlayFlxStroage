import motor.motor_asyncio
from config import Config

class Database:
    def __init__(self):
        self._client = None
        self.db = None
        self.collection = None

    async def connect(self):
        if Config.DATABASE_URL:
            print("Connecting to the database...")
            self._client = motor.motor_asyncio.AsyncIOMotorClient(Config.DATABASE_URL)
            self.db = self._client["StreamLinksDB"]
            self.collection = self.db["links"]
            print("✅ Database connection established.")
        else:
            print("⚠️ No DATABASE_URL - running without persistence")

    async def disconnect(self):
        if self._client:
            self._client.close()
            print("Database connection closed.")

    async def save_link(self, unique_id, message_id):
        if self.collection is not None:
            await self.collection.update_one(
                {'_id': unique_id},
                {'$set': {'message_id': message_id}},
                upsert=True
            )

    async def get_link(self, unique_id):
        if self.collection is not None:
            doc = await self.collection.find_one({'_id': unique_id})
            return doc.get('message_id') if doc else None
        return None

db = Database()