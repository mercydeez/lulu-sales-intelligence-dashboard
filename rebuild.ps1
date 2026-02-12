# Rebuild Script for Lulu Intelligence Dashboard
# Run this in PowerShell to rebuild the containers with latest code

Write-Host "=== Lulu Intelligence Dashboard Rebuild ===" -ForegroundColor Cyan
Write-Host ""

# Stop all containers
Write-Host "1. Stopping all containers..." -ForegroundColor Yellow
docker compose down

# Remove old images to force rebuild
Write-Host "2. Removing old images..." -ForegroundColor Yellow
docker rmi lulu-intelligence-dashboard-frontend -f 2>$null
docker rmi lulu-intelligence-dashboard-backend -f 2>$null

# Build without cache
Write-Host "3. Building containers (no cache)..." -ForegroundColor Yellow
docker compose build --no-cache

# Start containers
Write-Host "4. Starting containers..." -ForegroundColor Yellow
docker compose up -d

Write-Host ""
Write-Host "=== Build Complete ===" -ForegroundColor Green
Write-Host "Frontend: http://localhost:3000" -ForegroundColor Cyan
Write-Host "Backend:  http://localhost:8000" -ForegroundColor Cyan
Write-Host ""
Write-Host "Login with: atharva@lulu.ae / Lulu@2026!" -ForegroundColor White

# Wait for services to be ready
Write-Host ""
Write-Host "Waiting for services to start..." -ForegroundColor Yellow
Start-Sleep -Seconds 10

# Check status
docker compose ps
