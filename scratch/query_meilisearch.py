import asyncio
import httpx

async def main():
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                "http://localhost:8211/indexes/pms_test_contacts/search",
                json={"q": "", "limit": 10},
                headers={"Authorization": "Bearer dev_master_key_change_in_production"}
            )
            print("Meilisearch response:", resp.json())
        except Exception as e:
            print("Error:", e)

if __name__ == "__main__":
    asyncio.run(main())
