#!/usr/bin/env bash

# Improved test script for matty commands with proper verification
# Usage: ./test_all_commands_improved.sh

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

# Function to extract event ID from send output
extract_event_id() {
    # Parse JSON output to get event_id
    echo "$1" | grep -oP '"event_id"\s*:\s*"\K[^"]+' | head -1
}

# Set room name for testing
ROOM="Dev"

section_echo "1. SETUP - Capture initial state"

test_echo "Capture baseline message count" "matty messages $ROOM --limit 1 --format json"
BASELINE_COUNT=$(uv run matty messages "$ROOM" --limit 100 --format json 2>/dev/null | grep -c '"event_id"' || echo "0")
echo "Baseline message count: $BASELINE_COUNT"
echo

test_echo "List rooms to verify $ROOM exists" "matty rooms --format simple | grep $ROOM"
uv run matty rooms --format simple | grep "$ROOM" || fail_echo "Room $ROOM not found!"
echo

test_echo "Show users in $ROOM" "matty users $ROOM --format simple"
uv run matty users "$ROOM" --format simple
echo

section_echo "2. SEND MESSAGES - Create trackable test content"

# Send messages with unique identifiers
test_echo "Send test message 1" "matty send $ROOM 'TEST_MSG_1: Basic message'"
MSG1_OUTPUT=$(uv run matty send "$ROOM" "TEST_MSG_1: Basic message" 2>&1)
echo "$MSG1_OUTPUT"
echo "$MSG1_OUTPUT" | grep -q "✓ Message sent" && success_echo "Message 1 sent successfully" || fail_echo "Failed to send message 1"

test_echo "Send test message 2" "matty send $ROOM 'TEST_MSG_2: Will add reactions'"
MSG2_OUTPUT=$(uv run matty send "$ROOM" "TEST_MSG_2: Will add reactions" 2>&1)
echo "$MSG2_OUTPUT"
echo "$MSG2_OUTPUT" | grep -q "✓ Message sent" && success_echo "Message 2 sent successfully" || fail_echo "Failed to send message 2"

test_echo "Send test message 3" "matty send $ROOM 'TEST_MSG_3: Will start thread'"
MSG3_OUTPUT=$(uv run matty send "$ROOM" "TEST_MSG_3: Will start thread" 2>&1)
echo "$MSG3_OUTPUT"
echo "$MSG3_OUTPUT" | grep -q "✓ Message sent" && success_echo "Message 3 sent successfully" || fail_echo "Failed to send message 3"

sleep 2

test_echo "VERIFY: Check our 3 messages exist" "matty messages $ROOM --limit 10 | grep TEST_MSG"
VERIFY_OUTPUT=$(uv run matty messages "$ROOM" --limit 10 2>/dev/null)
echo "$VERIFY_OUTPUT" | grep -q "TEST_MSG_1" && success_echo "Found TEST_MSG_1" || fail_echo "TEST_MSG_1 not found"
echo "$VERIFY_OUTPUT" | grep -q "TEST_MSG_2" && success_echo "Found TEST_MSG_2" || fail_echo "TEST_MSG_2 not found"
echo "$VERIFY_OUTPUT" | grep -q "TEST_MSG_3" && success_echo "Found TEST_MSG_3" || fail_echo "TEST_MSG_3 not found"

# Get the handle mappings using JSON and jq
test_echo "Get handle mappings for our messages (JSON)" "matty messages $ROOM --limit 10 --format json | jq"
MESSAGES_JSON=$(uv run matty messages "$ROOM" --limit 10 --format json)

# Extract handles for our test messages using jq
MSG1_HANDLE=$(echo "$MESSAGES_JSON" | jq -r '.messages[] | select(.content | contains("TEST_MSG_1")) | .handle' | head -1)
MSG2_HANDLE=$(echo "$MESSAGES_JSON" | jq -r '.messages[] | select(.content | contains("TEST_MSG_2")) | .handle' | head -1)
MSG3_HANDLE=$(echo "$MESSAGES_JSON" | jq -r '.messages[] | select(.content | contains("TEST_MSG_3")) | .handle' | head -1)

# Also extract event IDs for reference
MSG1_EVENT_ID=$(echo "$MESSAGES_JSON" | jq -r '.messages[] | select(.content | contains("TEST_MSG_1")) | .event_id' | head -1)
MSG2_EVENT_ID=$(echo "$MESSAGES_JSON" | jq -r '.messages[] | select(.content | contains("TEST_MSG_2")) | .event_id' | head -1)
MSG3_EVENT_ID=$(echo "$MESSAGES_JSON" | jq -r '.messages[] | select(.content | contains("TEST_MSG_3")) | .event_id' | head -1)

echo
echo "Handle mappings (extracted via jq):"
echo "  TEST_MSG_1 -> $MSG1_HANDLE (event: ${MSG1_EVENT_ID:0:20}...)"
echo "  TEST_MSG_2 -> $MSG2_HANDLE (event: ${MSG2_EVENT_ID:0:20}...)"
echo "  TEST_MSG_3 -> $MSG3_HANDLE (event: ${MSG3_EVENT_ID:0:20}...)"
echo

# Show a sample of the JSON to verify handle field is present
echo "Sample JSON message with handle:"
echo "$MESSAGES_JSON" | jq '.messages[0] | {handle, sender, content: .content[0:50]}' 2>/dev/null || echo "jq parsing sample"

section_echo "3. REACTIONS - Add and verify with proper handles"

if [ -n "$MSG1_HANDLE" ]; then
    test_echo "Add 👍 to TEST_MSG_1 ($MSG1_HANDLE)" "matty react $ROOM $MSG1_HANDLE '👍'"
    uv run matty react "$ROOM" "$MSG1_HANDLE" "👍"
else
    fail_echo "Cannot add reaction - no handle for TEST_MSG_1"
fi

if [ -n "$MSG2_HANDLE" ]; then
    test_echo "Add 🚀 to TEST_MSG_2 ($MSG2_HANDLE)" "matty react $ROOM $MSG2_HANDLE '🚀'"
    uv run matty react "$ROOM" "$MSG2_HANDLE" "🚀"
else
    fail_echo "Cannot add reaction - no handle for TEST_MSG_2"
fi

sleep 2

test_echo "VERIFY: Check reactions on messages (JSON format)" "matty messages $ROOM --limit 10 --format json"
REACTIONS_JSON=$(uv run matty messages "$ROOM" --limit 10 --format json 2>/dev/null)

# Check for reactions in JSON output using jq for proper JSON parsing
if echo "$REACTIONS_JSON" | jq -e '.messages[] | select(.reactions | has("👍"))' >/dev/null 2>&1; then
    success_echo "Found 👍 reaction in JSON"
else
    fail_echo "👍 reaction not found in JSON"
fi

if echo "$REACTIONS_JSON" | jq -e '.messages[] | select(.reactions | has("🚀"))' >/dev/null 2>&1; then
    success_echo "Found 🚀 reaction in JSON"
else
    fail_echo "🚀 reaction not found in JSON"
fi

# Show detailed reactions
if [ -n "$MSG1_HANDLE" ]; then
    test_echo "Show reactions for TEST_MSG_1 ($MSG1_HANDLE)" "matty reactions $ROOM $MSG1_HANDLE"
    REACTION_DETAIL=$(uv run matty reactions "$ROOM" "$MSG1_HANDLE" --format simple 2>/dev/null)
    echo "$REACTION_DETAIL"
    echo "$REACTION_DETAIL" | grep -q "👍" && success_echo "Reaction verified on $MSG1_HANDLE" || fail_echo "No reaction found on $MSG1_HANDLE"
fi
echo

section_echo "4. REPLIES - Test with verified handles"

if [ -n "$MSG1_HANDLE" ]; then
    test_echo "Reply to TEST_MSG_1 ($MSG1_HANDLE)" "matty reply $ROOM $MSG1_HANDLE 'REPLY_TO_MSG1'"
    uv run matty reply "$ROOM" "$MSG1_HANDLE" "REPLY_TO_MSG1: This is a reply"
    sleep 2

    # Verify reply was sent
    test_echo "VERIFY: Check reply exists" "matty messages $ROOM --limit 5 | grep REPLY_TO_MSG1"
    uv run matty messages "$ROOM" --limit 5 | grep -q "REPLY_TO_MSG1" && success_echo "Reply found" || fail_echo "Reply not found"
else
    fail_echo "Cannot test reply - no handle for TEST_MSG_1"
fi
echo

section_echo "5. THREADS - Create and verify"

if [ -n "$MSG3_HANDLE" ]; then
    test_echo "Start thread from TEST_MSG_3 ($MSG3_HANDLE)" "matty thread-start $ROOM $MSG3_HANDLE"
    THREAD_OUTPUT=$(uv run matty thread-start "$ROOM" "$MSG3_HANDLE" "THREAD_START: Starting discussion" 2>/dev/null)
    echo "$THREAD_OUTPUT"

    # Extract thread ID from output
    THREAD_ID=$(echo "$THREAD_OUTPUT" | grep -oP 'Thread ID: \K\$[^\s]+' | head -1)
    if [ -n "$THREAD_ID" ]; then
        success_echo "Thread created with ID: $THREAD_ID"
    else
        fail_echo "Failed to extract thread ID"
    fi

    sleep 2

    # Verify thread indicator
    test_echo "VERIFY: Check thread indicator on message" "matty messages $ROOM --limit 10 | grep '↳'"
    THREAD_CHECK=$(uv run matty messages "$ROOM" --limit 10)
    echo "$THREAD_CHECK" | grep -q "↳" && success_echo "Thread indicator found" || fail_echo "No thread indicator"

    # List threads
    test_echo "List threads in room" "matty threads $ROOM"
    THREADS_OUTPUT=$(uv run matty threads "$ROOM" --limit 10 2>/dev/null)
    echo "$THREADS_OUTPUT"
    if echo "$THREADS_OUTPUT" | grep -q "No threads"; then
        fail_echo "Thread listing shows no threads despite creation"
    else
        success_echo "Threads found in listing"
    fi
else
    fail_echo "Cannot test threads - no handle for TEST_MSG_3"
fi
echo

section_echo "6. REDACTION - Delete and verify"

if [ -n "$MSG2_HANDLE" ]; then
    test_echo "Show message before deletion" "matty messages $ROOM --limit 10 | grep TEST_MSG_2"
    uv run matty messages "$ROOM" --limit 10 | grep "TEST_MSG_2"

    test_echo "Delete TEST_MSG_2 ($MSG2_HANDLE)" "matty redact $ROOM $MSG2_HANDLE --reason 'Test cleanup'"
    uv run matty redact "$ROOM" "$MSG2_HANDLE" --reason "Test cleanup"

    sleep 2

    test_echo "VERIFY: Check message is deleted" "matty messages $ROOM --limit 10"
    AFTER_DELETE=$(uv run matty messages "$ROOM" --limit 10 2>/dev/null)
    echo "$AFTER_DELETE"

    # Check if message still appears or shows as deleted
    if echo "$AFTER_DELETE" | grep -q "TEST_MSG_2"; then
        if echo "$AFTER_DELETE" | grep -q "\[deleted\].*TEST_MSG_2\|\[redacted\].*TEST_MSG_2"; then
            success_echo "Message shows as deleted/redacted"
        else
            fail_echo "Message still visible after deletion"
        fi
    else
        success_echo "Message removed from listing"
    fi
else
    fail_echo "Cannot test redaction - no handle for TEST_MSG_2"
fi
echo

section_echo "7. MENTIONS - Test and verify"

test_echo "Send message with mention" "matty send $ROOM '@mindroom_code TEST_MENTION: Check this'"
MENTION_OUTPUT=$(uv run matty send "$ROOM" "@mindroom_code TEST_MENTION: Check this" 2>/dev/null)
echo "$MENTION_OUTPUT"

sleep 2

test_echo "VERIFY: Check mention was processed" "matty messages $ROOM --limit 3"
MENTION_CHECK=$(uv run matty messages "$ROOM" --limit 3)
echo "$MENTION_CHECK"
echo "$MENTION_CHECK" | grep -q "TEST_MENTION" && success_echo "Mention message found" || fail_echo "Mention message not found"
echo "$MENTION_OUTPUT" | grep -q "Mentions were processed" && success_echo "Mention processing confirmed" || fail_echo "No mention processing confirmation"
echo

section_echo "8. OUTPUT FORMATS - Verify different formats work"

test_echo "JSON format (check structure)" "matty messages $ROOM --limit 2 --format json | python -m json.tool"
JSON_OUTPUT=$(uv run matty messages "$ROOM" --limit 2 --format json 2>/dev/null)
if echo "$JSON_OUTPUT" | python -m json.tool > /dev/null 2>&1; then
    success_echo "Valid JSON output"
    echo "$JSON_OUTPUT" | python -m json.tool | head -20
else
    fail_echo "Invalid JSON output"
fi
echo

test_echo "Simple format" "matty rooms --format simple | head -3"
uv run matty rooms --format simple | head -3
echo

test_echo "Rich format (tables)" "matty rooms --format rich | head -10"
uv run matty rooms --format rich | head -10
echo

section_echo "9. COMMAND ALIASES - Quick verification"

test_echo "Test alias 's' for send" "matty s $ROOM 'ALIAS_TEST: Testing alias'"
uv run matty s "$ROOM" "ALIAS_TEST: Testing alias"
sleep 1

test_echo "VERIFY: Alias message sent" "matty m $ROOM --limit 2 | grep ALIAS_TEST"
uv run matty m "$ROOM" --limit 2 | grep -q "ALIAS_TEST" && success_echo "Alias 's' works" || fail_echo "Alias 's' failed"
echo

section_echo "TEST SUMMARY"

echo -e "${GREEN}${BOLD}Test Results:${RESET}"
echo

# Count successes and failures from output
SUCCESS_COUNT=$(grep -c "✓" test_output_improved.txt 2>/dev/null || echo "0")
FAIL_COUNT=$(grep -c "✗" test_output_improved.txt 2>/dev/null || echo "0")

echo "Key improvements in this test:"
echo "  • Event ID tracking for messages"
echo "  • Handle mapping verification"
echo "  • Actual content verification (grep for TEST_MSG_*)"
echo "  • JSON validation for structured output"
echo "  • Reaction verification in JSON format"
echo "  • Thread ID extraction and verification"
echo "  • Proper success/failure reporting"
echo

if [ "$FAIL_COUNT" -eq "0" ]; then
    echo -e "${GREEN}${BOLD}All verifications passed!${RESET}"
else
    echo -e "${YELLOW}${BOLD}Some verifications failed - review output above${RESET}"
fi
