from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_clean_project_docs_exist():
    for rel_path in [
        "README.md",
        "AGENTS.md",
        "docs/AGENTFLOW.md",
        "docs/PROJECT_LAYOUT.md",
        "config/config.example.yaml",
    ]:
        assert (REPO_ROOT / rel_path).exists()


def test_readme_describes_agent_first_workflow():
    content = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for marker in [
        "PaperInsight AgentFlow",
        "paperinsight agent prepare",
        "paperinsight agent extract-metrics",
        "04_metrics_result.json",
        "paperinsight_report_",
        "MinerU",
        "Longcat",
    ]:
        assert marker in content


def test_agents_route_table_points_to_clean_layout():
    content = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for marker in [
        "docs/PROJECT_LAYOUT.md",
        "docs/AGENTFLOW.md",
        "paperinsight/cli.py",
        "paperinsight/agentflow/pipeline.py",
        "paperinsight/parser/mineru.py",
        "paperinsight/core/reporter.py",
    ]:
        assert marker in content
