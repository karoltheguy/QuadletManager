import asyncio
from services.ssh_manager import pool

async def test_ssh():
    print("Testing SSH connection to server 1...")
    try:
        out = await pool.execute_command(1, "echo Hello World")
        print("Success:", out.strip())
    except Exception:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_ssh())
