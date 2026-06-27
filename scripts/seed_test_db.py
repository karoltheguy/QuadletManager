import asyncio
import aiosqlite
import os

async def main():
    db_path = os.environ.get('QUADLET_DB_PATH', '/data/quadlets.db')
    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT COUNT(*) FROM servers") as cursor:
            count = (await cursor.fetchone())[0]
        
        if count == 0:
            await db.execute(
                "INSERT INTO servers (name, ip_address, ssh_user) VALUES (?, ?, ?)",
                ("Mock Server", "localhost", "root")
            )
            await db.commit()
            print("Database seeded with mock server.")
        else:
            print("Database already seeded. Skipping.")

if __name__ == "__main__":
    asyncio.run(main())
