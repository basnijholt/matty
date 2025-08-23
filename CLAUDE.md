# MatrixTUI Development Guidelines

## Core Philosophy

- **Simplicity First**: Build the simplest working solution
- **Functional Style**: Prefer functional programming over complex classes
- **Type Safety**: Use type hints and dataclasses over dictionaries
- **DRY Principle**: Don't repeat yourself - reuse code
- **Clean Code**: Remove unused imports, functions, and variables

## Development Workflow

### 1. Environment Setup
- Use `uv sync` to install dependencies
- Use `uv add <package>` to add new dependencies
- Use `uv add --dev <package>` for dev dependencies

### 2. Testing
- Run tests with `pytest` before claiming completion
- Use `uv run python matty.py` to test the client
- Use `uv run python test_client.py` for connection testing

### 3. Code Quality
- Run `pre-commit run --all-files` before committing
- Use type hints for all functions
- Avoid bare try-except blocks unless necessary
- Keep imports at the top of files

### 4. Git Workflow
- Make atomic commits (each commit should work)
- Never use `git add .` - add files individually
- Test before committing

## Matrix Client Specific

### Connection Details
- Server: `https://m-test.mindroom.chat`
- SSL Verify: false (test server)
- Test credentials in `.env` file

### Available Test Accounts
- See `.env` for usernames and passwords

## Running the Client

```bash
# Text-based client
uv run python matty.py

# Test connection
uv run python test_client.py
```

## Common Commands in Client
- `h` - Show help
- `r` - List rooms
- `s` - Select room
- `m` - Send message
- `u` - List users
- `q` - Quit
- Direct typing in room sends message
- `/message` - Quick send with /
