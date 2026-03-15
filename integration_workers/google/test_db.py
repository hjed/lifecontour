import asyncio

import asyncpg


async def test():
    try:
        conn = await asyncpg.connect(
            "postgresql://postgres:postgres@127.0.0.1:5943/personal_management_test"
        )
        print("Connected")
        await conn.close()
    except Exception as e:
        print(f"Failed: {e}")


asyncio.run(test())
