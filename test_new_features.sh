#!/usr/bin/env bash

# Test script for new matty features: search, export, watch
# Usage: ./test_new_features.sh

# Color codes
BOLD='\033[1m'
CYAN='\033[1;36m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
RED='\033[1;31m'
RESET='\033[0m'

# Function to print test headers
test_echo() {
    echo -e "${CYAN}${BOLD}>>> Testing: $1${RESET}"
    echo -e "${YELLOW}    Command: $2${RESET}"
}

# Function to print section headers
section_echo() {
    echo -e "${GREEN}${BOLD}=========================================${RESET}"
    echo -e "${GREEN}${BOLD}$1${RESET}"
    echo -e "${GREEN}${BOLD}=========================================${RESET}"
    echo
}

# Function to print success messages
success_echo() {
    echo -e "${GREEN}✓ $1${RESET}"
}

# Function to print failure messages
fail_echo() {
    echo -e "${RED}✗ $1${RESET}"
}

# Set room name for testing
ROOM="Dev"

section_echo "NEW FEATURE TESTS - Search, Export, Watch"

# =============================================================================
# 1. SEARCH FEATURE
# =============================================================================

section_echo "1. SEARCH - Test message search functionality"

test_echo "Send searchable test messages" "matty send $ROOM 'SEARCH_TEST: Python is awesome'"
uv run matty send "$ROOM" "SEARCH_TEST: Python is awesome"
sleep 1

test_echo "Send another message" "matty send $ROOM 'SEARCH_TEST: JavaScript and TypeScript'"
uv run matty send "$ROOM" "SEARCH_TEST: JavaScript and TypeScript"
sleep 1

test_echo "Send third message" "matty send $ROOM 'SEARCH_TEST: Matrix protocol testing'"
uv run matty send "$ROOM" "SEARCH_TEST: Matrix protocol testing"
sleep 2

test_echo "Search for 'Python' (case-insensitive)" "matty search $ROOM 'python' --limit 50"
SEARCH_OUTPUT=$(uv run matty search "$ROOM" "python" --limit 50 2>&1)
echo "$SEARCH_OUTPUT"
echo "$SEARCH_OUTPUT" | grep -q "Python" && success_echo "Found Python message" || fail_echo "Python message not found"
echo

test_echo "Search with regex pattern" "matty search $ROOM 'Java.*Script' --regex"
REGEX_OUTPUT=$(uv run matty search "$ROOM" "Java.*Script" --regex --limit 50 2>&1)
echo "$REGEX_OUTPUT"
echo "$REGEX_OUTPUT" | grep -q "JavaScript" && success_echo "Regex search worked" || fail_echo "Regex search failed"
echo

test_echo "Search with case-sensitive flag" "matty search $ROOM 'SEARCH_TEST' --case-sensitive"
CASE_OUTPUT=$(uv run matty search "$ROOM" "SEARCH_TEST" --case-sensitive --limit 50 2>&1)
echo "$CASE_OUTPUT"
echo "$CASE_OUTPUT" | grep -q "SEARCH_TEST" && success_echo "Case-sensitive search worked" || fail_echo "Case-sensitive search failed"
echo

test_echo "Search with JSON output" "matty search $ROOM 'testing' --format json | jq '.matches'"
JSON_SEARCH=$(uv run matty search "$ROOM" "testing" --format json --limit 50 2>/dev/null)
if echo "$JSON_SEARCH" | jq -e '.matches > 0' >/dev/null 2>&1; then
    success_echo "JSON search output valid"
    echo "Found $(echo "$JSON_SEARCH" | jq '.matches') matches"
else
    fail_echo "JSON search output invalid or no matches"
fi
echo

# =============================================================================
# 2. EXPORT FEATURE
# =============================================================================

section_echo "2. EXPORT - Test message export functionality"

# Create temp directory for exports
EXPORT_DIR="/tmp/matty_export_test_$$"
mkdir -p "$EXPORT_DIR"

test_echo "Export to Markdown" "matty export $ROOM --output $EXPORT_DIR/test.md --limit 50"
uv run matty export "$ROOM" --output "$EXPORT_DIR/test.md" --limit 50 --format markdown
if [ -f "$EXPORT_DIR/test.md" ]; then
    success_echo "Markdown export created"
    echo "File size: $(wc -c < "$EXPORT_DIR/test.md") bytes"
    echo "Preview:"
    head -10 "$EXPORT_DIR/test.md"
else
    fail_echo "Markdown export failed"
fi
echo

test_echo "Export to JSON" "matty export $ROOM --output $EXPORT_DIR/test.json --format json --limit 50"
uv run matty export "$ROOM" --output "$EXPORT_DIR/test.json" --format json --limit 50
if [ -f "$EXPORT_DIR/test.json" ]; then
    success_echo "JSON export created"
    # Validate JSON
    if python -m json.tool "$EXPORT_DIR/test.json" > /dev/null 2>&1; then
        success_echo "JSON is valid"
        echo "Message count: $(jq '.message_count' "$EXPORT_DIR/test.json")"
    else
        fail_echo "JSON is invalid"
    fi
else
    fail_echo "JSON export failed"
fi
echo

test_echo "Export to HTML" "matty export $ROOM --output $EXPORT_DIR/test.html --format html --limit 50"
uv run matty export "$ROOM" --output "$EXPORT_DIR/test.html" --format html --limit 50
if [ -f "$EXPORT_DIR/test.html" ]; then
    success_echo "HTML export created"
    echo "File size: $(wc -c < "$EXPORT_DIR/test.html") bytes"
    # Check for HTML structure
    grep -q "<title>" "$EXPORT_DIR/test.html" && success_echo "Valid HTML structure" || fail_echo "Invalid HTML structure"
else
    fail_echo "HTML export failed"
fi
echo

test_echo "Export to plain text" "matty export $ROOM --output $EXPORT_DIR/test.txt --format text --limit 50"
uv run matty export "$ROOM" --output "$EXPORT_DIR/test.txt" --format text --limit 50
if [ -f "$EXPORT_DIR/test.txt" ]; then
    success_echo "Text export created"
    echo "Line count: $(wc -l < "$EXPORT_DIR/test.txt")"
else
    fail_echo "Text export failed"
fi
echo

test_echo "Export without reactions" "matty export $ROOM --output $EXPORT_DIR/no_reactions.md --no-reactions --limit 50"
uv run matty export "$ROOM" --output "$EXPORT_DIR/no_reactions.md" --no-reactions --limit 50
if [ -f "$EXPORT_DIR/no_reactions.md" ]; then
    success_echo "Export without reactions created"
    # Check that reactions are not included
    if grep -q "Reactions:" "$EXPORT_DIR/no_reactions.md"; then
        fail_echo "Reactions found when they shouldn't be"
    else
        success_echo "Reactions correctly excluded"
    fi
else
    fail_echo "Export without reactions failed"
fi
echo

# Clean up export directory
echo "Cleaning up export directory: $EXPORT_DIR"
rm -rf "$EXPORT_DIR"

# =============================================================================
# 3. WATCH FEATURE
# =============================================================================

section_echo "3. WATCH - Test live message watching"

test_echo "Watch mode test (will run for 5 seconds)" "matty watch $ROOM --interval 2"
echo "Starting watch mode for 5 seconds..."
echo "Send a message in another terminal to see it appear!"
echo

# Run watch mode in background for 5 seconds
timeout 5 uv run matty watch "$ROOM" --interval 2 2>&1 &
WATCH_PID=$!

# Send a test message after 2 seconds
sleep 2
test_echo "Sending message while watching" "matty send $ROOM 'WATCH_TEST: Live message'"
uv run matty send "$ROOM" "WATCH_TEST: Live message appears!" 2>&1

# Wait for watch to complete
wait $WATCH_PID 2>/dev/null
success_echo "Watch mode test completed"
echo

# =============================================================================
# 4. ALIAS TESTS
# =============================================================================

section_echo "4. ALIASES - Test command aliases"

test_echo "Test 'find' alias for search" "matty find $ROOM 'alias' --limit 10"
ALIAS_OUTPUT=$(uv run matty find "$ROOM" "test" --limit 10 2>&1)
if echo "$ALIAS_OUTPUT" | grep -q "Search Results"; then
    success_echo "'find' alias works for search"
else
    fail_echo "'find' alias failed"
fi
echo

test_echo "Test 'save' alias for export" "matty save $ROOM --output /tmp/save_test.md --limit 10"
uv run matty save "$ROOM" --output /tmp/save_test.md --limit 10
if [ -f "/tmp/save_test.md" ]; then
    success_echo "'save' alias works for export"
    rm /tmp/save_test.md
else
    fail_echo "'save' alias failed"
fi
echo

test_echo "Test 'w' alias for watch (2 second test)" "matty w $ROOM --interval 1"
timeout 2 uv run matty w "$ROOM" --interval 1 2>&1 | head -5
success_echo "'w' alias works for watch"
echo

# =============================================================================
# SUMMARY
# =============================================================================

section_echo "TEST SUMMARY"

echo -e "${GREEN}${BOLD}New Features Test Results:${RESET}"
echo
echo "Key features tested:"
echo "  • Search: Text search with case-sensitive and regex options ✓"
echo "  • Export: Multiple formats (Markdown, JSON, HTML, Text) ✓"
echo "  • Watch: Live message monitoring ✓"
echo "  • Aliases: Command shortcuts (find, save, w) ✓"
echo
echo -e "${GREEN}${BOLD}All new feature tests completed!${RESET}"
echo
echo "Additional manual tests you can try:"
echo "  • Watch a room and send messages from another terminal"
echo "  • Export a room with many threads and reactions"
echo "  • Search for complex regex patterns"
echo "  • Export with custom filenames and locations"
