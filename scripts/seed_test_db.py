import asyncio
import aiosqlite
import os

async def main():
    db_path = os.environ.get('QUADLET_DB_PATH', '/data/quadlets.db')
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO servers (name, ip_address, ssh_user) VALUES (?, ?, ?)",
            ("Mock Server", "localhost", "root")
        )
        await db.commit()
    print("Database seeded with mock server.")

if __name__ == "__main__":
    asyncio.run(main())
