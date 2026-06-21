# boot-test.ps1 — proves a clean, from-scratch install boots without errors.
# Usage:  right-click > "Run with PowerShell"   OR   in a terminal:  .\boot-test.ps1
# Safe: it only rebuilds the local Docker stack. It does NOT touch git or your source files.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Say($msg, $color = "White") { Write-Host $msg -ForegroundColor $color }

Say "`n=== FORESIA CLEAN-BOOT TEST ===" "Cyan"
Say "This wipes the local DB volume and boots the stack from scratch.`n" "Gray"

# 1. Fresh start — wipe volumes so the backend re-seeds as if it's a brand-new machine.
#    We deliberately DO NOT start the frontend container: in dev you run `npm run dev`
#    on port 3000, and the container would collide with it. We bring up db + redis + backend.
Say "[1/5] Wiping volumes + starting fresh (db + redis + backend only)..." "Yellow"
docker compose down -v | Out-Null
docker compose up -d postgres redis backend

# 2. Wait for the backend to finish seeding the database (it seeds on startup).
#    We poll the users table until the 3 demo users appear, or time out.
Say "[2/5] Waiting for the backend to seed the database (up to 120s)..." "Yellow"
$dbOk = $false
foreach ($i in 1..60) {
    Start-Sleep -Seconds 2
    $health = (docker inspect --format '{{.State.Health.Status}}' sales_db 2>$null)
    if ($health -eq "healthy") {
        $u = (docker exec sales_db psql -U salesuser -d salesdb -tA -c "SELECT count(*) FROM users;" 2>$null)
        if ([int]$u -ge 3) { $dbOk = $true; break }   # seeding finished
    }
}

# 3. Scan the DB + backend logs for errors (seeding runs in the backend now)
Say "[3/5] Scanning db + backend logs for errors..." "Yellow"
$logs = (docker compose logs postgres backend 2>$null | Out-String)
$initErrors = ($logs -split "`n") | Where-Object { $_ -match "ERROR:|FATAL:|syntax error|ON_ERROR_STOP|Traceback|seeding failed" }

# 4. Verify the data actually landed (3 users, priced items, sales rows)
Say "[4/5] Verifying seeded data (users, prices, sales)..." "Yellow"
$userCount  = (docker exec sales_db psql -U salesuser -d salesdb -tA -c "SELECT count(*) FROM users;" 2>$null)
$priceCount = (docker exec sales_db psql -U salesuser -d salesdb -tA -c "SELECT count(*) FROM items WHERE unit_price_aed IS NOT NULL;" 2>$null)
$salesCount = (docker exec sales_db psql -U salesuser -d salesdb -tA -c "SELECT count(*) FROM sales;" 2>$null)

# 5. Check the web tiers respond
Say "[5/5] Checking backend + frontend respond..." "Yellow"
$backendOk = $false; $frontendOk = $false
try { $backendOk  = ((Invoke-WebRequest "http://localhost:8000/health" -TimeoutSec 5 -UseBasicParsing).StatusCode -eq 200) } catch {}
try { $frontendOk = ((Invoke-WebRequest "http://localhost:3000"        -TimeoutSec 8 -UseBasicParsing).StatusCode -eq 200) } catch {}

# ---- Report ----
Say "`n========== RESULT ==========" "Cyan"
$pass = $true
function Check($label, $ok, $detail) {
    if ($ok) { Say ("  PASS  " + $label + "  " + $detail) "Green" }
    else     { Say ("  FAIL  " + $label + "  " + $detail) "Red"; $script:pass = $false }
}
Check "Database healthy"       $dbOk                       ""
Check "No init errors in logs" ($initErrors.Count -eq 0)   $(if ($initErrors){"-> " + ($initErrors | Select-Object -First 1)})
Check "3 demo users seeded"    ([int]$userCount -ge 3)     "(found $userCount)"
Check "Items have prices"      ([int]$priceCount -gt 0)    "(found $priceCount)"
Check "Sales data loaded"      ([int]$salesCount -gt 0)    "(found $salesCount)"
Check "Backend /health 200"    $backendOk                  ""
Check "Frontend serves"        $frontendOk                 ""

Say "============================" "Cyan"
if ($pass) {
    Say "`nALL CHECKS PASSED — fresh install boots clean. This is the 'it's real' milestone.`n" "Green"
    Say "Open http://localhost:3000 and log in as yash@retaildemo.app / Demo@2026!`n" "Green"
} else {
    Say "`nSOME CHECKS FAILED — copy this output and send it to Claude; I'll diagnose the exact cause.`n" "Red"
}
