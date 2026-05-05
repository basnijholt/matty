"""Package structure compatibility tests."""

from typer.testing import CliRunner


def test_package_exports_existing_cli_symbols() -> None:
    from matty import Config, _load_config, app
    from matty.cli import app as cli_app

    assert app is cli_app
    assert Config.__name__ == "Config"
    assert callable(_load_config)


def test_tui_imports_from_package() -> None:
    from matty.tui import MattyApp

    assert MattyApp.__name__ == "MattyApp"


def test_cli_help_still_lists_existing_commands() -> None:
    from matty.cli import app

    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Functional Matrix CLI client" in result.output
    assert "rooms" in result.output
    assert "tui" in result.output


def test_cli_help_groups_commands_into_sections() -> None:
    from matty.cli import app

    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Setup" in result.output
    assert "Browse" in result.output
    assert "Messaging" in result.output
    assert "Threads" in result.output
    assert "Reactions" in result.output
    assert "Interface" in result.output
    assert "auth" in result.output
    assert "Manage Matrix authentication credentials." in result.output


def test_auth_help_has_message_and_sections() -> None:
    from matty.cli import app

    result = CliRunner().invoke(app, ["auth", "--help"])

    assert result.exit_code == 0
    assert "Manage Matrix authentication credentials." in result.output
    assert "SSO Login" in result.output
    assert "Direct Login" in result.output
    assert "Session" in result.output
