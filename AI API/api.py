# api.py
from fastapi import FastAPI, HTTPException, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import sys
from notion_client import Client as NotionClient
from typing import List, Dict
from collections import defaultdict
from neo4j import AsyncGraphDatabase

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
)

# MongoDB Configuration
MONGO_DETAILS = os.environ.get("MONGO_DETAILS", "mongodb://localhost:27017")
DATABASE_NAME = "areas_db"
COLLECTION_NAME = "areas"

# Neo4j Configuration (fail fast if missing)
NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USER = os.environ["NEO4J_USER"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]

@app.on_event("startup")
async def startup_db_client():
    app.mongodb_client = AsyncIOMotorClient(MONGO_DETAILS)
    app.mongodb = app.mongodb_client[DATABASE_NAME]
    print("Connected to MongoDB")

@app.on_event("shutdown")
async def shutdown_db_client():
    app.mongodb_client.close()
    print("Disconnected from MongoDB")

@app.on_event("startup")
async def startup_neo4j():
    app.neo4j_driver = AsyncGraphDatabase.driver(
        NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)
    )
    print("Connected to Neo4j")

@app.on_event("shutdown")
async def shutdown_neo4j():
    await app.neo4j_driver.close()
    print("Disconnected from Neo4j")

@app.get("/")
async def root():
    return {"message": "Welcome to the Areas of Human Existence API - Structured Version"}

@app.get("/areas-structured")
async def get_areas_structured():
    """Return hierarchy using 'Sub-item' relation property, excluding sub-areas."""
    collection = app.mongodb[COLLECTION_NAME]
    pages = [p async for p in collection.find({})]
    return _build_relation_hierarchy(pages)

@app.post("/notion-webhook")
async def notion_webhook(request: Request):
    payload = await request.json()
    print("Received Notion event (stdout):", payload)
    print("Received Notion event (stderr):", payload, file=sys.stderr)
    # Handle verification
    if "verification_token" in payload:
        return {"verification_token": payload["verification_token"]}
    # On any event, mirror the entire Notion database to MongoDB
    NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
    NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")
    notion = NotionClient(auth=NOTION_TOKEN)
    # Fetch all pages from the Notion database
    all_pages = []
    next_cursor = None
    while True:
        response = notion.databases.query(
            **{"database_id": NOTION_DATABASE_ID, "start_cursor": next_cursor} if next_cursor else {"database_id": NOTION_DATABASE_ID}
        )
        all_pages.extend(response["results"])
        if response.get("has_more"):
            next_cursor = response["next_cursor"]
        else:
            break
    # Prepare documents for MongoDB (use Notion page id as _id)
    docs = []
    for page in all_pages:
        doc = dict(page)
        doc["_id"] = page["id"]
        docs.append(doc)
    collection = app.mongodb[COLLECTION_NAME]
    # Clear the collection and insert all pages
    await collection.delete_many({})
    if docs:
        await collection.insert_many(docs)
    return {"ok": True, "mirrored": len(docs)}

@app.post("/graph/query")
async def run_cypher_query(query: str = Body(..., embed=True)):
    """Run an arbitrary Cypher query and return the result."""
    async with app.neo4j_driver.session() as session:
        result = await session.run(query)
        records = [record.data() async for record in result]
    return {"results": records}

@app.post("/graph/edge")
async def create_or_update_edge(
    source_id: str = Body(...),
    target_id: str = Body(...),
    rel_type: str = Body(...),
    properties: dict = Body(default={})
):
    """Create or update an edge (relationship) between two nodes."""
    cypher = (
        f"MATCH (a),(b) WHERE a.id = $source_id AND b.id = $target_id "
        f"MERGE (a)-[r:{rel_type}]->(b) "
        f"SET r += $properties RETURN a, r, b"
    )
    async with app.neo4j_driver.session() as session:
        result = await session.run(
            cypher, source_id=source_id, target_id=target_id, properties=properties
        )
        records = [record.data() async for record in result]
    return {"results": records}

def _plain_text_from_rich_text(rich_items: List[Dict]) -> str:
    """Helper to concatenate plain_text from Notion rich_text array."""
    return "".join(rt.get("plain_text", "") for rt in rich_items or [])

def _extract_simple_fields(page: Dict) -> Dict:
    """Extract public fields from a Notion page object."""
    props = page.get("properties", {})
    simple = {}
    # Extract Name (first title-type property)
    for prop_name, prop_val in props.items():
        if prop_val.get("type") == "title":
            simple["Name"] = _plain_text_from_rich_text(prop_val["title"])
            break
    # Extract Symbol (rich_text or select named "Symbol" if exists)
    if "Symbol" in props:
        sym_prop = props["Symbol"]
        if sym_prop.get("type") == "rich_text":
            simple["Symbol"] = _plain_text_from_rich_text(sym_prop["rich_text"])
        elif sym_prop.get("type") == "select":
            simple["Symbol"] = sym_prop["select"].get("name")
    # Extract Category (select or rich_text named "Category")
    if "Category" in props:
        cat_prop = props["Category"]
        if cat_prop.get("type") == "select":
            simple["Category"] = cat_prop["select"].get("name")
        elif cat_prop.get("type") == "rich_text":
            simple["Category"] = _plain_text_from_rich_text(cat_prop["rich_text"])
    # Fallback: include page id for reference
    simple["id"] = page.get("id")
    return simple

def _level_name(page: Dict) -> str:
    level_prop = page.get("properties", {}).get("Level")
    if level_prop and level_prop.get("type") == "select" and level_prop.get("select"):
        return level_prop["select"].get("name", "")
    return ""

def _is_sub_area(page: Dict) -> bool:
    return "sub" in _level_name(page).lower()

def _number_value(page: Dict) -> float:
    """Return numeric order from '#' property if present, else infinity."""
    num_prop = page.get("properties", {}).get("#")
    if num_prop and num_prop.get("type") == "number" and num_prop.get("number") is not None:
        return num_prop["number"]
    return float("inf")

def _build_relation_hierarchy(pages: List[Dict]) -> List[Dict]:
    """Build tree using 'Sub-item' relation graph, excluding Sub-Areas."""
    pages = [p for p in pages if not _is_sub_area(p)]
    id_to_page: Dict[str, Dict] = {p["id"]: p for p in pages}
    id_to_node: Dict[str, Dict] = {}

    def node_for(pid: str) -> Dict:
        if pid not in id_to_node:
            page = id_to_page[pid]
            n = _extract_simple_fields(page)
            n["children"] = []
            n["_number"] = _number_value(page)
            id_to_node[pid] = n
        return id_to_node[pid]

    child_ids = set()
    for p in pages:
        rel_prop = p.get("properties", {}).get("Sub-item")
        if rel_prop and rel_prop.get("type") == "relation":
            parent_node = node_for(p["id"])
            for rel in rel_prop.get("relation", []):
                cid = rel.get("id")
                if cid in id_to_page:
                    child_ids.add(cid)
                    parent_node["children"].append(node_for(cid))

    roots = [node for pid, node in id_to_node.items() if pid not in child_ids]

    def sort_children(node: Dict):
        node["children"].sort(key=lambda c: (c.get("_number", float("inf")), c.get("Name", "")))
        for c in node["children"]:
            sort_children(c)
    for r in roots:
        sort_children(r)

    def prune(node: Dict):
        node.pop("_number", None)
        if not node["children"]:
            node.pop("children", None)
        else:
            for c in node["children"]:
                prune(c)
    for r in roots:
        prune(r)

    roots.sort(key=lambda c: (c.get("_number", float("inf")), c.get("Name", "")))
    return roots

# Lanza:  uvicorn api:app --port 8000 --reload