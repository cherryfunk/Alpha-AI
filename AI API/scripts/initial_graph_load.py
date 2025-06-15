import os
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from neo4j import AsyncGraphDatabase

MONGO_URI = os.environ.get("MONGO_DETAILS", "mongodb://localhost:27017")
MONGO_DB_NAME = os.environ.get("DATABASE_NAME", "areas_db")

# Node label mapping by depth
LABELS = ["Conjunction", "Group", "Area"]

async def create_node_and_children(session, node, depth, parent_id=None):
    label = LABELS[depth]
    node_id = node["id"]
    name = node.get("Name")
    # Create node
    await session.run(
        f"MERGE (n:{label} {{id: $id}}) SET n.Name = $name",
        id=node_id,
        name=name,
    )
    # Create relationship to parent if not top-level
    if parent_id is not None:
        parent_label = LABELS[depth-1]
        rel_type = (
            "HAS_GROUP" if label == "Group" else
            "HAS_AREA" if label == "Area" else
            "HAS_CHILD"
        )
        await session.run(
            f"MATCH (p:{parent_label} {{id: $parent_id}}), (c:{label} {{id: $child_id}}) "
            f"MERGE (p)-[:{rel_type}]->(c)",
            parent_id=parent_id,
            child_id=node_id,
        )
    # Recurse for children
    children = node.get("children", [])
    if depth+1 < len(LABELS):
        for child in children:
            await create_node_and_children(session, child, depth+1, node_id)

async def load_tree():
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    mongo_db = mongo_client[MONGO_DB_NAME]
    collection = mongo_db["areas"]
    docs = [doc async for doc in collection.find({})]

    neo4j_driver = AsyncGraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
    )
    async with neo4j_driver.session() as session:
        # Ensure unique constraints
        for label in LABELS:
            await session.run(
                f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE"
            )
        # Recursively create nodes and relationships
        for doc in docs:
            await create_node_and_children(session, doc, 0)
    await neo4j_driver.close()
    mongo_client.close()
    print("✔ Initial graph load complete.")

if __name__ == "__main__":
    asyncio.run(load_tree()) 