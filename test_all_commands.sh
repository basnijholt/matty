#!/usr/bin/env bash

# Test script for all matty commands
# Usage: ./test_all_commands.sh

# Color codes
BOLD='\033[1m'
CYAN='\033[1;36m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
RESET='\033[0m'

# Function to print test headers in bold cyan
test_echo() {
    echo -e "${CYAN}${BOLD}>>> Testing: $1${RESET}"
    echo -e "${YELLOW}    Command: $2${RESET}"
}

# Function to print section headers in bold green
section_echo() {
    echo -e "${GREEN}${BOLD}=========================================${RESET}"
    echo -e "${GREEN}${BOLD}$1${RESET}"
    echo -e "${GREEN}${BOLD}=========================================${RESET}"
    echo
}

section_echo "Testing all matty commands"

# Set room name for testing
ROOM="News"

test_echo "Show help" "matty --help"
uv run matty --help | head -5
echo

test_echo "List all rooms" "matty rooms --format simple"
uv run matty rooms --format simple | head -5
echo

test_echo "List rooms (alias)" "matty r --format simple"
uv run matty r --format simple | head -3
echo

test_echo "Show messages in $ROOM" "matty messages $ROOM --limit 3"
uv run matty messages "$ROOM" --limit 3
echo

test_echo "Show messages (alias)" "matty m $ROOM --limit 2"
uv run matty m "$ROOM" --limit 2
echo

test_echo "Show users in $ROOM" "matty users $ROOM --format simple"
uv run matty users "$ROOM" --format simple
echo

test_echo "Show users (alias)" "matty u $ROOM --format simple"
uv run matty u "$ROOM" --format simple | head -3
echo

test_echo "Send message to $ROOM" "matty send $ROOM 'Test message from script'"
uv run matty send "$ROOM" "Test message from script"
echo

test_echo "Send message (alias)" "matty s $ROOM 'Test with alias'"
uv run matty s "$ROOM" "Test with alias"
echo

test_echo "List threads in $ROOM" "matty threads $ROOM --limit 5"
uv run matty threads "$ROOM" --limit 5
echo

test_echo "List threads (alias)" "matty t $ROOM --limit 3 --format simple"
uv run matty t "$ROOM" --limit 3 --format simple
echo

test_echo "Show thread messages" "matty thread $ROOM t1 --limit 5"
uv run matty thread "$ROOM" t1 --limit 5 2>/dev/null || echo "No thread t1 found (expected)"
echo

test_echo "Show thread (alias)" "matty th $ROOM t6 --limit 3"
uv run matty th "$ROOM" t6 --limit 3 2>/dev/null || echo "Thread t6 may not exist"
echo

test_echo "Reply to message m1" "matty reply $ROOM m1 'Test reply from script'"
uv run matty reply "$ROOM" m1 "Test reply from script"
echo

test_echo "Reply (alias)" "matty re $ROOM m2 'Test reply with alias'"
uv run matty re "$ROOM" m2 "Test reply with alias"
echo

test_echo "Start thread from m3" "matty thread-start $ROOM m3 'Starting thread from script'"
uv run matty thread-start "$ROOM" m3 "Starting thread from script"
echo

test_echo "Start thread (alias)" "matty ts $ROOM m4 'Thread start with alias'"
uv run matty ts "$ROOM" m4 "Thread start with alias"
echo

test_echo "Reply in thread t6" "matty thread-reply $ROOM t6 'Thread reply from script'"
uv run matty thread-reply "$ROOM" t6 "Thread reply from script" 2>/dev/null || echo "Thread t6 may not exist"
echo

test_echo "Thread reply (alias)" "matty tr $ROOM t6 'Thread reply with alias'"
uv run matty tr "$ROOM" t6 "Thread reply with alias" 2>/dev/null || echo "Thread t6 may not exist"
echo

section_echo "Testing different output formats"

test_echo "Rich format (default)" "matty rooms --format rich"
uv run matty rooms --format rich | head -8
echo

test_echo "Simple format" "matty rooms --format simple"
uv run matty rooms --format simple | head -3
echo

test_echo "JSON format" "matty messages $ROOM --limit 2 --format json"
uv run matty messages "$ROOM" --limit 2 --format json | head -15
echo

section_echo "Testing with mentions"

test_echo "Send with @mention" "matty send $ROOM '@mindroom_news Test mention from script'"
uv run matty send "$ROOM" "@mindroom_news Test mention from script"
echo

section_echo "All commands tested!"
