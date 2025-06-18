import os
import asyncio
from typing import List, Dict, Any, Optional

from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient
from neo4j import AsyncGraphDatabase
import httpx

# ----- CONFIG ------------------------------------------------------------
MONGO_URI = os.environ.get("MONGO_DETAILS", "mongodb://localhost:27017")
MONGO_DB = os.environ.get("DATABASE_NAME", "areas_db")
AREAS_COLLECTION = "areas"  # still used just to get a change-stream trigger

NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USER = os.environ["NEO4J_USER"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]

LABELS = ["Conjunction", "Group", "Area"]  # depth 0,1,2(+)

# If you want a fresh graph on every full-document update set this to true/1
FULL_REFRESH = os.environ.get("NEO4J_FULL_REFRESH", "0") in {"1", "true", "True"}

# FastAPI endpoint that returns the fully structured tree (same shape as sample_areas.json)
AREAS_API = os.environ.get("AREAS_API", "https://fastapi-areas-app-782958835263.us-central1.run.app/areas-structured")

# Motor / PyMongo error classes for robust retry logic
from pymongo.errors import PyMongoError, OperationFailure

# ------------------------------------------------------------------------
app = FastAPI()


@app.get("/")
async def root():
    return {"status": "ok"}


# -------------------- Neo4j helpers --------------------------------------

async def merge_node(session, label: str, node_id: str, name: Optional[str]):
    """MERGE a node by id and set its human-readable name property."""
    cypher = f"MERGE (n:{label} {{id:$id}}) SET n.name = $name"
    await session.run(cypher, id=node_id, name=name)


async def merge_relationship(
    session,
    parent_label: str,
    child_label: str,
    parent_id: str,
    child_id: str,
):
    if child_label == "Group":
        rel = "HAS_GROUP"
    elif child_label == "Area":
        rel = "HAS_AREA"
    else:
        rel = "HAS_CHILD"
    cypher = (
        f"MATCH (p:{parent_label} {{id:$pid}}), (c:{child_label} {{id:$cid}})"
        f" MERGE (p)-[:{rel}]->(c)"
    )
    await session.run(cypher, pid=parent_id, cid=child_id)


async def create_subtree(
    session,
    node: Dict[str, Any],
    depth: int = 0,
    parent_id: Optional[str] = None,
):
    label = LABELS[depth] if depth < len(LABELS) else LABELS[-1]
    node_id = node["id"]
    name = node.get("Name") or node.get("name")

    await merge_node(session, label, node_id, name)

    if parent_id is not None:
        parent_label = LABELS[depth - 1] if depth - 1 < len(LABELS) else LABELS[-1]
        await merge_relationship(session, parent_label, label, parent_id, node_id)

    for child in node.get("children", []):
        await create_subtree(session, child, depth + 1, node_id)


async def clear_graph(session):
    await session.run("MATCH (n) DETACH DELETE n")


# -------------------- fetch helper --------------------------------------

async def fetch_tree() -> List[Dict[str, Any]]:
    """Retrieve the nested Conjunction → Group → Area tree from FastAPI."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(AREAS_API)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict):
                # endpoint may wrap list in {"data": [...]}
                data = data.get("data") or data.get("results") or []
            return data if isinstance(data, list) else []
    except Exception as exc:
        print(f"[ERROR] fetch_tree failed: {exc}")
        return []


# -------------------- Mongo change-stream handler ------------------------

async def handle_change(change, neo_session):
    # On ANY change event simply pull the latest structured tree from the API
    roots = await fetch_tree()
    if not roots:
        print("[WARN] fetch_tree returned no roots; skipping change event")
        return

    if FULL_REFRESH:
        await clear_graph(neo_session)

    for root in roots:
        await neo_session.run("MATCH (n:Conjunction {id:$id}) DETACH DELETE n", id=root["id"])
        await create_subtree(neo_session, root)


# -------------------- Worker task ---------------------------------------

async def watch_areas_collection():
    """Continuously watch the MongoDB collection and sync changes to Neo4j.

    The function retries forever; if the change-stream cursor becomes
    non-resumable (e.g. oplog history lost, CursorNotFound, network split) we
    sleep a bit and start a fresh stream so the task never crashes.
    """

    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[MONGO_DB]
    collection = db[AREAS_COLLECTION]

    neo4j_driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    # ---------- one-time graph init & back-fill --------------------------
    async with neo4j_driver.session() as neo_session:
        # Ensure constraints
        for lbl in LABELS:
            await neo_session.run(
                f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{lbl}) REQUIRE n.id IS UNIQUE"
            )
        print("[INFO] Performing initial back-fill via /areas-structured …")
        roots = await fetch_tree()
        for root in roots:
            await create_subtree(neo_session, root)

    # ---------- continuous change-stream loop ---------------------------
    while True:
        try:
            async with collection.watch(full_document="updateLookup") as stream:
                async with neo4j_driver.session() as neo_session:
                    async for change in stream:
                        try:
                            await handle_change(change, neo_session)
                        except Exception as exc:
                            print(f"[ERROR] failed to process change: {exc}\n{change}")
        except OperationFailure as exc:
            # code 286 (ChangeStreamHistoryLost) cannot be resumed — start fresh
            print(f"[WARN] change-stream operation failure ({exc.code}): {exc}. Restarting in 2 s …")
            await asyncio.sleep(2)
        except PyMongoError as exc:
            # Generic PyMongo errors: log and retry
            print(f"[WARN] PyMongo error while tailing change-stream: {exc}. Retrying in 5 s …")
            await asyncio.sleep(5)
        except Exception as exc:
            # Catch-all so the task never dies
            print(f"[ERROR] Unexpected error in change-stream loop: {exc}. Retrying in 5 s …")
            await asyncio.sleep(5)


# -------------------- FastAPI startup -----------------------------------

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(watch_areas_collection()) 