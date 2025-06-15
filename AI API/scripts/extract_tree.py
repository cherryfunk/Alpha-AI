import json
from pathlib import Path

DATA_PATH = Path(__file__).parent / "sample_areas.json"

with DATA_PATH.open() as f:
    data = json.load(f)

conjunctions = []  # list of (id, name)
groups = []        # list of (id, name, parent_id)
areas = []         # list of (id, name, parent_id)

def walk(node, depth, parent_id=None):
    if depth == 0:
        conjunctions.append((node["id"], node["Name"]))
    elif depth == 1:
        groups.append((node["id"], node["Name"], parent_id))
    else:
        areas.append((node["id"], node["Name"], parent_id))
    for child in node.get("children", []):
        walk(child, depth + 1, node["id"])

for root in data:
    walk(root, 0)

print("Conjunctions (count =", len(conjunctions), "):")
for cid, name in conjunctions:
    print(f"  - {name} ({cid})")

print("\nGroups (count =", len(groups), "):")
for gid, name, parent in groups:
    print(f"  - {name} ({gid}) <- parent Conjunction {parent}")

print("\nAreas (count =", len(areas), "):")
for aid, name, parent in areas:
    print(f"  - {name} ({aid}) <- parent Group {parent}") 