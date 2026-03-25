"""
CLI 启动引导相关测试。
"""

from typer.testing import CliRunner

from paperinsight.cli import app


runner = CliRunner()


def test_root_command_shows_startup_guide():
    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert "Quick start" in result.stdout
    assert "paperinsight config" in result.stdout
    assert "paperinsight analyze <pdf-dir>" in result.stdout


def test_analyze_help_keeps_command_usage_clean():
    result = runner.invoke(app, ["analyze", "--help"])

    assert result.exit_code == 0
    assert "Quick start" not in result.stdout
    assert "PDF" in result.stdout
    assert "--rename-pdfs" in result.stdout
