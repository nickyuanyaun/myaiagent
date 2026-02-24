#!/bin/bash

# ==========================================
# MyAIAgent One-Click Updater (macOS/Linux)
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
echo -e "${CYAN}      MyAIAgent One-Click Updater        ${NC}"
echo -e "${CYAN}==========================================${NC}"
echo ""

# 1. Pull Latest Changes
echo -e "${YELLOW}[1/3] Fetching latest code from GitHub...${NC}"
if [ -d ".git" ]; then
    git pull
    echo -e "${GREEN}Code updated successfully.${NC}"
else
    echo -e "${RED}Error: This directory is not a Git repository.${NC}"
    exit 1
fi

# 2. Update Virtual Environment
echo -e "${YELLOW}[2/3] refreshing isolated Python environment...${NC}"
if [ -d "venv" ]; then
    source venv/bin/activate
    echo -e "${GREEN}Virtual environment activated.${NC}"
else
    echo -e "${YELLOW}Virtual environment not found. Creating a new one...${NC}"
    python3 -m venv venv
    source venv/bin/activate
fi

# 3. Refresh Dependencies
echo -e "${YELLOW}[3/3] Updating dependencies...${NC}"
pip install --upgrade pip
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
    echo -e "${GREEN}Dependencies updated successfully.${NC}"
else
    echo -e "${RED}Warning: requirements.txt not found!${NC}"
fi

echo ""
echo -e "${CYAN}==========================================${NC}"
echo -e "${GREEN}✅ Update Complete!${NC}"
echo ""
echo -e "You can now restart your Agent:"
echo -e "  ${YELLOW}python main.py${NC}"
echo -e "${CYAN}==========================================${NC}"
