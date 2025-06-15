import os
import json
from pathlib import Path
import asyncio
from neo4j import AsyncGraphDatabase

DATA_PATH = Path(__file__).parent / "sample_areas.json"

LABELS = ["Conjunction", "Group", "Area"]

async def create_node_and_children(session, node, depth, parent_id=None):
    label = LABELS[depth] if depth < len(LABELS) else LABELS[-1]
    node_id = node["id"]
    name = node["Name"]
    await session.run(
        f"MERGE (n:{label} {{id:$id}}) SET n.name=$name",
        id=node_id,
        name=name,
    )
    if parent_id:
        parent_label = LABELS[depth-1] if depth-1 < len(LABELS) else LABELS[-1]
        rel = "HAS_GROUP" if label == "Group" else "HAS_AREA" if label == "Area" else "HAS_CHILD"
        await session.run(
            f"MATCH (p:{parent_label} {{id:$pid}}), (c:{label} {{id:$cid}}) MERGE (p)-[:{rel}]->(c)",
            pid=parent_id,
            cid=node_id,
        )
    for child in node.get("children", []):
        await create_node_and_children(session, child, depth+1, node_id)

async def main():
    with DATA_PATH.open() as f:
        roots = json.load(f)

    driver = AsyncGraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
    )
    async with driver.session() as session:
        # constraints
        for label in LABELS:
            await session.run(
                f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE"
            )
        # optional: clear existing graph
        detach = os.environ.get("CLEAR_GRAPH", "0") in {"1","true","True"}
        if detach:
            await session.run("MATCH (n) DETACH DELETE n")
        # load data
        for root in roots:
            await create_node_and_children(session, root, 0)
    await driver.close()

if __name__ == "__main__":
    asyncio.run(main()) 