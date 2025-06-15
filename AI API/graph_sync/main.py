import os
import asyncio
import signal
from motor.motor_asyncio import AsyncIOMotorClient
from neo4j import AsyncGraphDatabase
from fastapi import FastAPI

# Map MongoDB collection names to Neo4j labels
COLLECTION_LABELS = {
    "areas": "Area",
    "groups": "Group",
    "conjunctions": "Conjunction",
}

MONGO_URI = os.environ.get("MONGO_DETAILS", "mongodb://localhost:27017")
MONGO_DB_NAME = os.environ.get("DATABASE_NAME", "areas_db")

DETACH_DELETE = os.environ.get("NEO4J_DETACH_DELETE", "1") in {"1", "true", "True"}

app = FastAPI()

@app.get("/")
async def root():
    return {"status": "ok"}

async def process_change(change: dict, label: str, session):
    """Apply a single MongoDB change-stream event to Neo4j."""
    op = change["operationType"]

    if op in {"insert", "replace"}:
        doc = change["fullDocument"]
        doc_id = str(doc["_id"])
        props = {k: v for k, v in doc.items() if k != "_id"}
        await session.run(
            f"MERGE (n:{label} {{id:$id}}) SET n += $props",
            id=doc_id,
            props=props,
        )

    elif op == "update":
        doc_id = str(change["documentKey"]["_id"])
        updated = change["updateDescription"]["updatedFields"]
        removed = change["updateDescription"]["removedFields"]
        if updated:
            await session.run(
                f"MATCH (n:{label} {{id:$id}}) SET n += $props",
                id=doc_id,
                props=updated,
            )
        for field in removed:
            await session.run(
                f"MATCH (n:{label} {{id:$id}}) REMOVE n.{field}",
                id=doc_id,
            )

    elif op == "delete":
        doc_id = str(change["documentKey"]["_id"])
        delete_cypher = (
            f"MATCH (n:{label} {{id:$id}}) {'DETACH DELETE' if DETACH_DELETE else 'DELETE'} n"
        )
        await session.run(delete_cypher, id=doc_id)

async def watch_collection(db, coll_name: str, label: str, neo4j_driver):
    """Watch a single MongoDB collection and apply events to Neo4j."""
    collection = db[coll_name]
    async with collection.watch(full_document='updateLookup') as stream:
        async with neo4j_driver.session() as session:
            async for change in stream:
                try:
                    await process_change(change, label, session)
                except Exception as exc:
                    # Log & continue (primitive logging to stdout)
                    print(f"[ERROR] Failed processing change: {exc}\nChange: {change}")

async def worker():
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[MONGO_DB_NAME]

    neo4j_driver = AsyncGraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
    )

    # Ensure constraints exist before streaming
    async with neo4j_driver.session() as session:
        for label in COLLECTION_LABELS.values():
            await session.run(
                f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE"
            )

    # Spawn one task per collection
    watch_tasks = [
        asyncio.create_task(watch_collection(db, coll, label, neo4j_driver))
        for coll, label in COLLECTION_LABELS.items()
    ]

    # Wait forever (until cancelled)
    try:
        await asyncio.gather(*watch_tasks)
    except asyncio.CancelledError:
        pass
    finally:
        await neo4j_driver.close()
        mongo_client.close()

@app.on_event("startup")
async def start_worker():
    loop = asyncio.get_event_loop()
    loop.create_task(worker()) 