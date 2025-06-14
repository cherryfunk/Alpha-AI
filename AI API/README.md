# Areas API - Structured Version

This API provides a structured view of areas of human existence, synced with a Notion database.

## Local Development

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set up environment variables:
```bash
export MONGO_DETAILS="your_mongodb_connection_string"
export NOTION_TOKEN="your_notion_token"
export NOTION_DATABASE_ID="your_notion_database_id"
```

3. Run the API:
```bash
uvicorn api:app --host 0.0.0.0 --port 8080
```

## Docker Build

1. Build the Docker image:
```bash
docker build -t areas-api .
```

2. Run the container:
```bash
docker run -p 8080:8080 \
  -e MONGO_DETAILS="your_mongodb_connection_string" \
  -e NOTION_TOKEN="your_notion_token" \
  -e NOTION_DATABASE_ID="your_notion_database_id" \
  areas-api
```

## Google Cloud Run Deployment

1. Install and initialize the Google Cloud SDK.

2. Set up Cloud Build variables:
```bash
gcloud builds submit --config=cloudbuild.yaml \
  --substitutions=_MONGO_DETAILS="your_mongodb_connection_string",_NOTION_TOKEN="your_notion_token",_NOTION_DATABASE_ID="your_notion_database_id"
```

## API Endpoints

- `GET /`: Welcome message
- `GET /areas-structured`: Get the hierarchical structure of areas
- `POST /notion-webhook`: Webhook endpoint for Notion sync

## Environment Variables

- `MONGO_DETAILS`: MongoDB connection string
- `NOTION_TOKEN`: Notion API token
- `NOTION_DATABASE_ID`: ID of the Notion database to sync with 