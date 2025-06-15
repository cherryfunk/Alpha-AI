import os
import asyncio
import uuid
from motor.motor_asyncio import AsyncIOMotorClient
from neo4j import AsyncGraphDatabase

MONGO_URI = os.environ.get("MONGO_DETAILS", "mongodb://localhost:27017")
MONGO_DB_NAME = os.environ.get("DATABASE_NAME", "areas_db")

async def main():
    # Setup clients
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    mongo_db = mongo_client[MONGO_DB_NAME]
    areas = mongo_db["areas"]

    neo4j_driver = AsyncGraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
    )

    # Insert test doc
    test_id = str(uuid.uuid4())
    await areas.insert_one({"_id": test_id, "name": "SyncTest"})

    # Poll Neo4j for up to 10 seconds
    found = False
    for _ in range(20):
        async with neo4j_driver.session() as session:
            res = await session.run("MATCH (n:Area {id:$id}) RETURN n", id=test_id)
            record = await res.single()
            if record:
                found = True
                break
        await asyncio.sleep(0.5)

    # Cleanup
    await areas.delete_one({"_id": test_id})
    mongo_client.close()
    await neo4j_driver.close()

    if not found:
        raise SystemExit("❌ Node did not sync to Neo4j within timeout")
    print("✅ Mongo → Neo4j sync verified")

if __name__ == "__main__":
    asyncio.run(main()) 