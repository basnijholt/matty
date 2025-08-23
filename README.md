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

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd matrixtui

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

### CLI Commands

```bash
# List all rooms
uv run python matrix_cli.py rooms

# Show users in a room
uv run python matrix_cli.py users lobby

# Get recent messages from a room
uv run python matrix_cli.py messages lobby --limit 10

# List threads in a room
uv run python matrix_cli.py threads lobby

# View messages in a specific thread
uv run python matrix_cli.py thread lobby <thread_id>

# Send a message to a room
uv run python matrix_cli.py send lobby "Hello from CLI!"

# Use different output formats
uv run python matrix_cli.py rooms --format json
uv run python matrix_cli.py rooms --format simple
```

### Command Options

All commands support:
- `--username/-u` - Override username from environment
- `--password/-p` - Override password from environment
- `--format/-f` - Output format (rich/simple/json)

## Project Structure

```
matrixtui/
├── matrix_cli.py         # Main CLI application (functional style)
├── test_client.py        # Connection testing utility
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
# Test connection
uv run python test_client.py

# Run pre-commit checks
uv run pre-commit run --all-files
```

## License

MIT