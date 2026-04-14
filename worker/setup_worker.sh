#!/bin/bash
echo "=== Sentrix AI Worker Setup ==="
echo ""
read -p "Enter Hub URL (e.g. https://yourserver.com): " HUB_URL
read -p "Enter your Client API Key: " CLIENT_API_KEY
read -p "Enter a label for this worker (e.g. Main Entrance): " WORKER_LABEL
read -p "Enter camera RTSP URLs (comma separated): " CAMERA_URLS
read -p "Enter camera names (comma separated, same order): " CAMERA_NAMES
read -p "Media server port (default 8765): " MEDIA_PORT
MEDIA_PORT=${MEDIA_PORT:-8765}

cat > .env << EOF
HUB_URL=${HUB_URL}
CLIENT_API_KEY=${CLIENT_API_KEY}
WORKER_LABEL=${WORKER_LABEL}
CAMERA_URLS=${CAMERA_URLS}
CAMERA_NAMES=${CAMERA_NAMES}
MEDIA_SERVER_PORT=${MEDIA_PORT}
SNAPSHOT_DIR=/app/snapshots
EOF

echo ""
echo "Configuration saved to .env"
echo "Starting worker..."
docker compose -f docker-compose.worker.yml up -d --build
echo ""
echo "Worker started. Check status: docker compose -f docker-compose.worker.yml logs -f"
