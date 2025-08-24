#!/usr/bin/env python3
"""Script to reorganize tests into logical files."""

import re
from pathlib import Path

# Map of test classes to their new files
TEST_ORGANIZATION = {
    "tests/test_state.py": [
        "TestStateManagement",
        "TestMessageHandles",
        "TestThreadManagement",
        "TestPydanticModels",
        "TestConfigLoading",
    ],
    "tests/test_display.py": [
        "TestDisplayFunctions",
    ],
    "tests/test_messaging.py": [
        "TestMatrixProtocolHelpers",
        "TestMentionParsing",
        "TestThreadHandling",
    ],
    "tests/test_cli.py": [
        "TestCLIValidation",
        "TestCLICommands",
        "TestAsyncCommandExecution",
    ],
    "tests/test_client.py": [
        "TestClientCreation",
        "TestErrorHandling",
    ],
}


def extract_class(content, class_name):
    """Extract a test class and its imports from file content."""
    # Find the class definition
    pattern = rf"^class {class_name}.*?(?=^class |\Z)"
    match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
    if match:
        return match.group(0)
    return None


def extract_imports(content):
    """Extract import statements from file content."""
    imports = []
    for line in content.split("\n"):
        if line.startswith(("import ", "from ")) and not line.startswith("from ."):
            imports.append(line)
        elif not line.strip() or line.startswith("#"):
            continue
        else:
            # Stop at first non-import line
            break
    return imports


def main():
    # Read the main test file
    test_file = Path("tests/test_coverage_improvements.py")
    content = test_file.read_text()

    # Extract imports
    imports = extract_imports(content)

    # Create new test files
    for new_file, classes in TEST_ORGANIZATION.items():
        new_path = Path(new_file)

        # Start with docstring and imports
        file_content = [
            f'"""Tests for {new_path.stem.replace("test_", "").replace("_", " ")}."""',
            "",
        ]

        # Add imports (will deduplicate later)
        file_content.extend(imports)
        file_content.append("")
        file_content.append("")

        # Add each test class
        for class_name in classes:
            class_content = extract_class(content, class_name)
            if class_content:
                file_content.append(class_content)

        # Write the new file
        new_path.write_text("\n".join(file_content))
        print(f"Created {new_file} with classes: {', '.join(classes)}")


if __name__ == "__main__":
    main()
