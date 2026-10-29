#!/usr/bin/env bash
# ==============================================================================
# All-In-One Demonstration & Validation Runner
# ==============================================================================
# Executes the entire prediction market arbitrage suite in sequence:
#   1. Unit Test Suite (15 automated test cases)
#   2. Historical Tick-by-Tick Market Replay (Real Kalshi depth)
#   3. Microstructure Benchmark & Diminishing Return Capacity Curve
#   4. Live Kalshi Public Exchange Scanner
# ==============================================================================

set -e

# Terminal formatting
BOLD="\033[1m"
GREEN="\033[32m"
CYAN="\033[36m"
YELLOW="\033[33m"
RESET="\033[0m"

echo -e "${BOLD}${CYAN}======================================================================${RESET}"
echo -e "${BOLD}${CYAN}  PREDICTION MARKET COMBINATORIAL ARBITRAGE ENGINE - SHOWCASE RUNNER  ${RESET}"
echo -e "${BOLD}${CYAN}======================================================================${RESET}"

# 1. Automated Test Suite
echo -e "\n${BOLD}${YELLOW}[STEP 1/4] Running Automated Test Suite (15 Test Cases)...${RESET}"
python3 -m unittest discover -s tests -p "test_*.py" -v

# 2. Historical Real-World Replay
echo -e "\n${BOLD}${YELLOW}[STEP 2/4] Executing Real-World Historical Event Replay (SP500 Depth)...${RESET}"
python3 main.py --mode replay

# 3. Benchmark & Capacity Curve
echo -e "\n${BOLD}${YELLOW}[STEP 3/4] Running Synthetic Microstructure Benchmark & Capacity Curves...${RESET}"
python3 main.py --mode benchmark

# 4. Live Public Scanner
echo -e "\n${BOLD}${YELLOW}[STEP 4/4] Scanning Live Public Kalshi Markets for Arbitrage Mispricings...${RESET}"
python3 main.py --mode live

echo -e "\n${BOLD}${GREEN}======================================================================${RESET}"
echo -e "${BOLD}${GREEN}  ALL CHECKS AND SIMULATION RUNS COMPLETED SUCCESSFULLY [PASS]        ${RESET}"
echo -e "${BOLD}${GREEN}======================================================================${RESET}\n"
