import os
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from neo4j import AsyncGraphDatabase

# Mapping from Mongo collection name to Neo4j node label
COLLECTION_LABELS = {
    "areas": "Area",
    "groups": "Group",
    "conjunctions": "Conjunction",
}

MONGO_URI = os.environ.get("MONGO_DETAILS", "mongodb://localhost:27017")
MONGO_DB_NAME = os.environ.get("DATABASE_NAME", "areas_db")

async def load_nodes():
    """Back-fill Neo4j with nodes from MongoDB collections."""
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    mongo_db = mongo_client[MONGO_DB_NAME]

    neo4j_driver = AsyncGraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
    )

    async with neo4j_driver.session() as session:
        # Ensure unique constraints exist for each label
        for label in COLLECTION_LABELS.values():
            await session.run(
                f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE"
            )

        # Load each collection
        for coll_name, label in COLLECTION_LABELS.items():
            print(f"Loading collection '{coll_name}' into label '{label}' …")
            collection = mongo_db[coll_name]
            async for doc in collection.find({}):
                doc_id = str(doc.get("_id"))
                # Exclude the Mongo _id from properties (store others as-is)
                properties = {k: v for k, v in doc.items() if k != "_id"}
                await session.run(
                    f"MERGE (n:{label} {{id:$id}}) SET n += $props",
                    id=doc_id,
                    props=properties,
                )

    await neo4j_driver.close()
    mongo_client.close()
    print("✔ Initial graph load complete.")

if __name__ == "__main__":
    asyncio.run(load_nodes()) 