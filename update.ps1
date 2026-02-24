<#
.SYNOPSIS
MyAIAgent One-Click Updater for Windows
#>

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "      MyAIAgent One-Click Updater        " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# 1. Pull Latest Changes
Write-Host "[1/3] Fetching latest code from GitHub..." -ForegroundColor Yellow
if (Test-Path ".git") {
    git pull
    Write-Host "Code updated successfully." -ForegroundColor Green
}
else {
    Write-Host "Error: This directory is not a Git repository." -ForegroundColor Red
    exit
}

# 2. Update Virtual Environment
Write-Host "[2/3] Refreshing isolated Python environment..." -ForegroundColor Yellow
if (Test-Path "venv") {
    if (Test-Path "venv\Scripts\Activate.ps1") {
        . .\venv\Scripts\Activate.ps1
        Write-Host "Virtual environment activated." -ForegroundColor Green
    }
}
else {
    Write-Host "Virtual environment not found. Creating a new one..." -ForegroundColor Yellow
    python -m venv venv
    . .\venv\Scripts\Activate.ps1
}

# 3. Refresh Dependencies
Write-Host "[3/3] Updating dependencies..." -ForegroundColor Yellow
python -m pip install --upgrade pip
if (Test-Path "requirements.txt") {
    pip install -r requirements.txt
    Write-Host "Dependencies updated successfully." -ForegroundColor Green
}
else {
    Write-Host "Warning: requirements.txt not found!" -ForegroundColor Red
}

Write-Host "`n==========================================" -ForegroundColor Cyan
Write-Host "✅ Update Complete!" -ForegroundColor Green
Write-Host "`nYou can now restart your Agent:"
Write-Host "  python main.py" -ForegroundColor Yellow
Write-Host "==========================================" -ForegroundColor Cyan
