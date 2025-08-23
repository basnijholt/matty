# Matrix CLI Client

A simple, functional Matrix chat client built with Python, Typer, and Rich. Perfect for AI-driven automation - every interaction is a single CLI command.

## Features

- Fast CLI commands for quick Matrix operations
- Thread support - view and navigate threaded conversations
- AI-friendly - every action is a single CLI command
- Functional programming style (minimal classes, maximum functions)
- Environment-based configuration
- Multiple output formats (rich, simple, JSON)
- Type-safe with dataclasses and type hints
- Persistent simple ID mapping for complex Matrix IDs

## Installation

```bash
# Clone the repository
git clone https://github.com/basnijholt/matrix-cli
cd matrix-cli

# Install dependencies with uv
uv sync

# Optional: Install pre-commit hooks
uv run pre-commit install
```

## Configuration

Create a `.env` file with your Matrix credentials:

```bash
MATRIX_HOMESERVER=https://matrix.org
MATRIX_USERNAME=your_username
MATRIX_PASSWORD=your_password
MATRIX_SSL_VERIFY=true  # Set to false for test servers
```

## Usage

### Available Commands

<!-- markdown-code-runner -->
```bash
python matrix_cli.py --help
```
<!-- markdown-code-runner -->

### Rooms Command

List all joined Matrix rooms:

<!-- markdown-code-runner -->
```bash
python matrix_cli.py rooms --help
```
<!-- markdown-code-runner -->

### Messages Command

Get recent messages from a room:

<!-- markdown-code-runner -->
```bash
python matrix_cli.py messages --help
```
<!-- markdown-code-runner -->

### Users Command

List users in a room:

<!-- markdown-code-runner -->
```bash
python matrix_cli.py users --help
```
<!-- markdown-code-runner -->

### Thread Commands

View and interact with threads:

<!-- markdown-code-runner -->
```bash
python matrix_cli.py threads --help
```
<!-- markdown-code-runner -->

<!-- markdown-code-runner -->
```bash
python matrix_cli.py thread --help
```
<!-- markdown-code-runner -->

### Send Command

Send messages to rooms:

<!-- markdown-code-runner -->
```bash
python matrix_cli.py send --help
```
<!-- markdown-code-runner -->

### Reply Command

Reply to messages:

<!-- markdown-code-runner -->
```bash
python matrix_cli.py reply --help
```
<!-- markdown-code-runner -->

### Thread Start Command

Start a thread from a message:

<!-- markdown-code-runner -->
```bash
python matrix_cli.py thread-start --help
```
<!-- markdown-code-runner -->

### Thread Reply Command

Reply in a thread:

<!-- markdown-code-runner -->
```bash
python matrix_cli.py thread-reply --help
```
<!-- markdown-code-runner -->

## Examples

### Basic Usage

```bash
# List all rooms
uv run python matrix_cli.py rooms

# Show users in a room
uv run python matrix_cli.py users lobby

# Get recent messages from a room
uv run python matrix_cli.py messages lobby --limit 10

# Send a message to a room
uv run python matrix_cli.py send lobby "Hello from CLI!"

# Use different output formats
uv run python matrix_cli.py rooms --format json
uv run python matrix_cli.py rooms --format simple
```

### Working with Threads

```bash
# List threads in a room
uv run python matrix_cli.py threads lobby

# View messages in a specific thread (using simple ID)
uv run python matrix_cli.py thread lobby t1

# Start a thread from a message
uv run python matrix_cli.py thread-start lobby m2 "Starting a thread!"

# Reply in a thread (using simple thread ID)
uv run python matrix_cli.py thread-reply lobby t1 "Reply in thread"
```

### Message Handles and Replies

```bash
# Reply to a message using handle
uv run python matrix_cli.py reply lobby m3 "This is a reply!"

# Reply to the 5th message in a room
uv run python matrix_cli.py messages lobby --limit 10
uv run python matrix_cli.py reply lobby m5 "Replying to message 5"
```

## Message Handles and Thread IDs

The CLI uses convenient handles to reference messages and threads:

- **Message handles**: `m1`, `m2`, `m3`, etc. - Reference messages by their position
- **Thread IDs**: `t1`, `t2`, `t3`, etc. - Reference threads with simple persistent IDs

These IDs are stored in `~/.matrix_cli_ids.json` and persist across sessions.

### Why Simple IDs?

Matrix uses complex IDs like:
- Event: `$Uj2XuH2a8EqJBh4g:matrix.org`
- Room: `!DfQvqvwXYsFjVcfLTp:matrix.org`

Our CLI simplifies these to:
- Messages: `m1`, `m2`, `m3` (temporary handles for current view)
- Threads: `t1`, `t2`, `t3` (persistent IDs across sessions)

## Output Formats

The CLI supports three output formats:

1. **Rich** (default) - Beautiful terminal UI with tables and colors
2. **Simple** - Plain text output, perfect for scripts
3. **JSON** - Machine-readable format for automation

Example:
```bash
# Pretty tables with colors
uv run python matrix_cli.py rooms

# Simple text output
uv run python matrix_cli.py rooms --format simple

# JSON for automation
uv run python matrix_cli.py rooms --format json | jq '.[] | .name'
```

## Project Structure

```
matrix-cli/
├── matrix_cli.py         # Main CLI application (functional style)
├── test_client.py        # Connection testing utility
├── tests/                # Test suite
│   ├── __init__.py
│   ├── conftest.py       # Pytest configuration
│   └── test_matrix_cli.py # Unit tests
├── .github/              # GitHub Actions workflows
│   └── workflows/
│       ├── pytest.yml    # Test runner
│       ├── release.yml   # PyPI release
│       └── markdown-code-runner.yml # README updater
├── .env                  # Your credentials (not in git)
├── .env.example          # Example environment file
├── CLAUDE.md            # Development guidelines
├── pyproject.toml       # Project configuration
└── README.md            # This file
```

## Development

This project follows functional programming principles:
- Private functions (`_function_name`) for internal logic
- Dataclasses over dictionaries for data structures
- Type hints everywhere for clarity
- No unnecessary abstractions or class hierarchies
- Functions over classes where possible

See `CLAUDE.md` for detailed development guidelines.

## Testing

```bash
# Run tests
uv run pytest tests/ -v

# Test with coverage
uv run pytest tests/ -v --cov=matrix_cli --cov-report=term-missing

# Test connection to Matrix server
uv run python test_client.py

# Run pre-commit checks
uv run pre-commit run --all-files
```

## License

MIT
