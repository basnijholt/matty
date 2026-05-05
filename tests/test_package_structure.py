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
