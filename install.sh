#!/bin/bash

# ==========================================
# MyAIAgent One-Click Installer (macOS/Linux)
# ==========================================

# Error handling
set -e

# ANSI Colors
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}==========================================${NC}"
echo -e "${CYAN}  Welcome to MyAIAgent One-Click Installer${NC}"
echo -e "${CYAN}==========================================${NC}"
echo ""

# 1. Dependency Checks
echo -e "${YELLOW}[1/5] Checking dependencies...${NC}"

# Check for Git
if ! command -v git &> /dev/null; then
    echo -e "${RED}Error: 'git' is not installed.${NC}"
    echo -e "Please install git first. (e.g. 'brew install git' or 'sudo apt install git')"
    exit 1
fi

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: 'python3' is not installed.${NC}"
    echo -e "Please install python3 first."
    exit 1
fi

echo -e "${GREEN}Dependencies OK.${NC}"

# 2. Clone Repository
echo -e "${YELLOW}[2/5] Fetching latest code...${NC}"
TARGET_DIR="myaiagent"

if [ -d "$TARGET_DIR" ]; then
    echo -e "Directory '$TARGET_DIR' already exists. Updating..."
    cd $TARGET_DIR
    git pull
else
    git clone https://github.com/nickyuanyaun/myaiagent.git $TARGET_DIR
    cd $TARGET_DIR
fi

echo -e "${GREEN}Code fetched successfully.${NC}"

# 3. Create Virtual Environment
echo -e "${YELLOW}[3/5] Setting up isolated Python environment...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "${GREEN}Virtual environment created.${NC}"
else
    echo -e "${GREEN}Virtual environment already exists.${NC}"
fi

# 4. Install Dependencies
echo -e "${YELLOW}[4/5] Installing Python packages...${NC}"
source venv/bin/activate
pip install --upgrade pip
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
    echo -e "${GREEN}Packages installed successfully.${NC}"
else
    echo -e "${RED}Warning: requirements.txt not found!${NC}"
fi

# 5. Web-based Configuration Setup
echo -e "${YELLOW}[5/5] Launching Configuration Web UI...${NC}"

if [ -f ".env" ]; then
    echo -e "${GREEN}.env file already exists. Skipping configuration.${NC}"
else
    echo -e "${CYAN}Opening your browser for setup... (http://localhost:8080)${NC}"
    python3 setup_ui.py
fi

# Finished!
echo ""
echo -e "${CYAN}==========================================${NC}"
echo -e "${GREEN}✅ Installation Complete!${NC}"
echo ""
echo -e "To start your AI Agent, run:"
echo -e "  ${YELLOW}cd $TARGET_DIR${NC}"
echo -e "  ${YELLOW}source venv/bin/activate${NC}"
echo -e "  ${YELLOW}python main.py${NC}"
echo ""
echo -e "Enjoy!"
echo -e "${CYAN}==========================================${NC}"
