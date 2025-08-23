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

<!-- [[[cog
import subprocess
result = subprocess.run(["python", "matrix_cli.py", "--help"], capture_output=True, text=True)
print("```")
print(result.stdout.strip())
print("```")
]]] -->
```

```
<!-- [[[end]]] -->

### Rooms Command

List all joined Matrix rooms:

<!-- [[[cog
import subprocess
result = subprocess.run(["python", "matrix_cli.py", "rooms", "--help"], capture_output=True, text=True)
print("```")
print(result.stdout.strip())
print("```")
]]] -->
```

```
<!-- [[[end]]] -->

### Messages Command

Get recent messages from a room:

<!-- [[[cog
import subprocess
result = subprocess.run(["python", "matrix_cli.py", "messages", "--help"], capture_output=True, text=True)
print("```")
print(result.stdout.strip())
print("```")
]]] -->
```

```
<!-- [[[end]]] -->

### Thread Commands

View and interact with threads:

<!-- [[[cog
import subprocess
result = subprocess.run(["python", "matrix_cli.py", "threads", "--help"], capture_output=True, text=True)
print("```")
print(result.stdout.strip())
print("```")
]]] -->
```

```
<!-- [[[end]]] -->

### Send Command

Send messages to rooms:

<!-- [[[cog
import subprocess
result = subprocess.run(["python", "matrix_cli.py", "send", "--help"], capture_output=True, text=True)
print("```")
print(result.stdout.strip())
print("```")
]]] -->
```

```
<!-- [[[end]]] -->

## Examples

```bash
# List all rooms
uv run python matrix_cli.py rooms

# Show users in a room
uv run python matrix_cli.py users lobby

# Get recent messages from a room
uv run python matrix_cli.py messages lobby --limit 10

# List threads in a room
uv run python matrix_cli.py threads lobby

# View messages in a specific thread (using simple ID)
uv run python matrix_cli.py thread lobby t1

# Send a message to a room
uv run python matrix_cli.py send lobby "Hello from CLI!"

# Reply to a message using handle
uv run python matrix_cli.py reply lobby m3 "This is a reply!"

# Start a thread from a message
uv run python matrix_cli.py thread-start lobby m2 "Starting a thread!"

# Reply in a thread (using simple thread ID)
uv run python matrix_cli.py thread-reply lobby t1 "Reply in thread"

# Use different output formats
uv run python matrix_cli.py rooms --format json
uv run python matrix_cli.py rooms --format simple
```

## Message Handles and Thread IDs

The CLI uses convenient handles to reference messages and threads:

- **Message handles**: `m1`, `m2`, `m3`, etc. - Reference messages by their position
- **Thread IDs**: `t1`, `t2`, `t3`, etc. - Reference threads with simple persistent IDs

These IDs are stored in `~/.matrix_cli_ids.json` and persist across sessions.

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

# Test connection
uv run python test_client.py

# Run pre-commit checks
uv run pre-commit run --all-files
```

## License

MIT
