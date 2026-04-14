Write-Host "=== Sentrix AI Worker Setup ===" -ForegroundColor Cyan
$HUB_URL = Read-Host "Enter Hub URL (e.g. https://yourserver.com)"
$CLIENT_API_KEY = Read-Host "Enter your Client API Key"
$WORKER_LABEL = Read-Host "Enter a label for this worker (e.g. Main Entrance)"
$CAMERA_URLS = Read-Host "Enter camera RTSP URLs (comma separated)"
$CAMERA_NAMES = Read-Host "Enter camera names (comma separated)"
$MEDIA_PORT = Read-Host "Media server port (press Enter for 8765)"
if (-not $MEDIA_PORT) { $MEDIA_PORT = "8765" }

@"
HUB_URL=$HUB_URL
CLIENT_API_KEY=$CLIENT_API_KEY
WORKER_LABEL=$WORKER_LABEL
CAMERA_URLS=$CAMERA_URLS
CAMERA_NAMES=$CAMERA_NAMES
MEDIA_SERVER_PORT=$MEDIA_PORT
SNAPSHOT_DIR=/app/snapshots
"@ | Out-File -FilePath ".env" -Encoding UTF8

Write-Host "Configuration saved. Starting worker..." -ForegroundColor Green
docker compose -f docker-compose.worker.yml up -d --build
Write-Host "Worker started!" -ForegroundColor Green
