<#
.SYNOPSIS
MyAIAgent One-Click Installer for Windows
#>

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Welcome to MyAIAgent One-Click Installer" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# 1. Dependency Checks
Write-Host "[1/5] Checking dependencies..." -ForegroundColor Yellow

# Check for Git
if (-not (Get-Command "git" -ErrorAction SilentlyContinue)) {
    Write-Host "Error: 'git' is not installed." -ForegroundColor Red
    Write-Host "Please install Git for Windows first (https://gitforwindows.org/)"
    exit
}

# Check for Python
if (-not (Get-Command "python" -ErrorAction SilentlyContinue)) {
    Write-Host "Error: 'python' is not installed or not in PATH." -ForegroundColor Red
    Write-Host "Please install Python 3.10+ (https://www.python.org/downloads/)"
    exit
}

Write-Host "Dependencies OK." -ForegroundColor Green

# 2. Clone Repository
Write-Host "[2/5] Fetching latest code..." -ForegroundColor Yellow
$TargetDir = "myaiagent"

if (Test-Path $TargetDir) {
    Write-Host "Directory '$TargetDir' already exists. Updating..."
    Set-Location $TargetDir
    git pull
} else {
    git clone https://github.com/nickyuanyaun/myaiagent.git $TargetDir
    Set-Location $TargetDir
}

Write-Host "Code fetched successfully." -ForegroundColor Green

# 3. Create Virtual Environment
Write-Host "[3/5] Setting up isolated Python environment..." -ForegroundColor Yellow
if (-not (Test-Path "venv")) {
    python -m venv venv
    Write-Host "Virtual environment created." -ForegroundColor Green
} else {
    Write-Host "Virtual environment already exists." -ForegroundColor Green
}

# 4. Install Dependencies
Write-Host "[4/5] Installing Python packages..." -ForegroundColor Yellow

# Temporarily execute the activation script in the current process
if (Test-Path "venv\Scripts\Activate.ps1") {
    . .\venv\Scripts\Activate.ps1
} else {
    Write-Host "Warning: Could not find venv activation script." -ForegroundColor Red
}

python -m pip install --upgrade pip
if (Test-Path "requirements.txt") {
    pip install -r requirements.txt
    Write-Host "Packages installed successfully." -ForegroundColor Green
} else {
    Write-Host "Warning: requirements.txt not found!" -ForegroundColor Red
}

# 5. Interactive Configuration (.env Setup)
Write-Host "[5/5] Configuring environment variables..." -ForegroundColor Yellow

if (Test-Path ".env") {
    Write-Host ".env file already exists. Skipping configuration." -ForegroundColor Green
} else {
    Write-Host "Let's set up your API keys." -ForegroundColor Cyan
    Write-Host "(You can find your Telegram token from @BotFather, and Gemini key from Google AI Studio)`n"
    
    $TgToken = Read-Host "Enter your Telegram Bot Token"
    $GoogleKey = Read-Host "Enter your Google Gemini API Key"
    $UserId = Read-Host "Enter your Telegram User ID (e.g. 12345678)"

    $EnvContent = @"
TELEGRAM_BOT_TOKEN=$TgToken
ALLOWED_USER_IDS=$UserId
GOOGLE_API_KEY=$GoogleKey
METUBE_URL=http://localhost:8081
WP_URL=https://your-wordpress-site.com
WP_USER=admin
WP_PASSWORD=your_app_password
"@
    
    Set-Content -Path ".env" -Value $EnvContent -Encoding UTF8
    Write-Host ".env configuration saved successfully!" -ForegroundColor Green
}

# Finished!
Write-Host "`n==========================================" -ForegroundColor Cyan
Write-Host "✅ Installation Complete!" -ForegroundColor Green
Write-Host "`nTo start your AI Agent, run:"
Write-Host "  cd $TargetDir" -ForegroundColor Yellow
Write-Host "  .\venv\Scripts\Activate.ps1" -ForegroundColor Yellow
Write-Host "  python main.py" -ForegroundColor Yellow
Write-Host "`nEnjoy!"
Write-Host "==========================================" -ForegroundColor Cyan
