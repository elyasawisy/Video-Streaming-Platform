param(
    [string]$Env = "dev"
)

function Usage {
    Write-Host "Usage: .\deploy.ps1 [-Env dev|prod]"
    Exit 1
}

if ($Env -ne 'dev' -and $Env -ne 'prod') {
    Usage
}

Write-Host "Deploying $Env environment..."

# Determine paths
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..")
Set-Location $ProjectRoot
Write-Host "Project root: $ProjectRoot"

$overall_status = 0

Write-Host "Bringing down existing stacks (clean volumes)..."
docker-compose down -v 2>$null

Write-Host "Starting services for $Env..."
if ($Env -eq 'prod') {
    & docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
    if ($LASTEXITCODE -ne 0) { $overall_status = 1 }
} else {
    & docker-compose -f docker-compose.yml -f docker-compose.override.yml up -d
    if ($LASTEXITCODE -ne 0) { $overall_status = 1 }
}

Write-Host "Running database migrations..."
& python -c "import importlib; importlib.import_module('alembic')" 2>$null
if ($LASTEXITCODE -eq 0) {
    & python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { $overall_status = 1 }
} else {
    Write-Host "alembic not found. Attempting to install from requirements.txt..."
    Write-Host "Attempting to install alembic locally (only) to run migrations..."
    & python -m pip install --upgrade pip setuptools wheel > $null 2>&1
    & python -m pip install alembic==1.12.1 SQLAlchemy==2.0.23 > $null 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to install alembic (or SQLAlchemy) in host environment." -ForegroundColor Yellow
        Write-Host "Common on Windows when building binary deps. To run migrations, execute them inside a container instead:" -ForegroundColor Yellow
        Write-Host "  docker-compose run --rm upload_service_http2 python -m alembic upgrade head" -ForegroundColor Yellow
        Write-Host "or" -ForegroundColor Yellow
        Write-Host "  docker-compose run --rm streaming_service python -m alembic upgrade head" -ForegroundColor Yellow
        $overall_status = 1
    } else {
        & python -c "import importlib; importlib.import_module('alembic')" 2>$null
        if ($LASTEXITCODE -eq 0) {
            & python -m alembic upgrade head
            if ($LASTEXITCODE -ne 0) { $overall_status = 1 }
        }
    }
}

Write-Host "Verifying deployment with health checks (retrying until services are ready)..."
$maxAttempts = 12
$attempt = 0
$healthy = $false
while ($attempt -lt $maxAttempts) {
    Write-Host "Healthcheck attempt $($attempt + 1)/$maxAttempts..."
    & python src/shared/healthcheck.py
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Health checks passed"
        $healthy = $true
        break
    }
    Start-Sleep -Seconds 5
    $attempt++
}
if (-not $healthy) {
    Write-Host "Health checks failed after $maxAttempts attempts." -ForegroundColor Red
    $overall_status = 1
}

if ($overall_status -eq 0) {
    Write-Host "Deployment successful!"
    exit 0
} else {
    Write-Host "Deployment failed! Check service logs for details." -ForegroundColor Red
    exit 1
}
