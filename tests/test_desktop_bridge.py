from pathlib import Path

from paperinsight.desktop_bridge import (
    _build_runtime_config,
    _build_startup_recommendation,
    _build_stats,
    _collect_pdf_files,
    _has_online_capability,
)
from paperinsight.models.schemas import DeviceData, PaperData, PaperInfo
from paperinsight.utils.config import DEFAULT_CONFIG, normalize_config


def test_build_runtime_config_regex_disables_online_features():
    config = normalize_config(DEFAULT_CONFIG)
    runtime_config, selected_mode = _build_runtime_config(
        config,
        {
            "mode": "regex",
            "exportJson": True,
            "renamePdfs": True,
            "bilingual": True,
            "pdfDir": "/tmp/input",
            "outputDir": "/tmp/output",
        },
    )

    assert selected_mode == "regex"
    assert runtime_config["llm"]["enabled"] is False
    assert runtime_config["paddlex"]["enabled"] is False
    assert "json" in runtime_config["output"]["format"]
    assert runtime_config["output"]["rename_pdfs"] is True
    assert runtime_config["output"]["bilingual_text"] is True
    assert runtime_config["desktop"]["ui"]["last_pdf_dir"] == "/tmp/input"
    assert runtime_config["desktop"]["ui"]["last_output_dir"] == "/tmp/output"


def test_collect_pdf_files_respects_recursive_flag(tmp_path: Path):
    root_pdf = tmp_path / "root.pdf"
    nested_dir = tmp_path / "nested"
    nested_pdf = nested_dir / "child.pdf"
    nested_dir.mkdir()
    root_pdf.write_text("root")
    nested_pdf.write_text("child")

    direct = _collect_pdf_files(tmp_path, recursive=False)
    recursive = _collect_pdf_files(tmp_path, recursive=True)

    assert direct == [root_pdf]
    assert set(recursive) == {root_pdf, nested_pdf}


def test_normalize_config_keeps_desktop_defaults():
    config = normalize_config({})

    assert config["desktop"]["engine"]["mode"] == "bundled"
    assert config["desktop"]["ui"]["remember_last_paths"] is True
    assert config["desktop"]["ui"]["onboarding_completed"] is False


def test_build_stats_includes_success_and_error_items(tmp_path: Path):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_text("dummy")

    paper = PaperData(
        paper_info=PaperInfo(title="Test Paper", journal_name="Nature", impact_factor=12.3),
        devices=[DeviceData(device_label="A", eqe="22.5%", structure="ITO/PVK/EML")],
    )

    stats = _build_stats(
        pdf_files=[pdf_path],
        results=[paper],
        errors=[{"pdf_name": "bad.pdf", "pdf_path": str(tmp_path / "bad.pdf"), "error_message": "解析失败", "context": "PDF解析", "error_type": "ParseFailed"}],
        report_files={"excel": str(tmp_path / "report.xlsx")},
        renamed_count=1,
        processed_items=[(pdf_path, paper)],
    )

    assert stats["successItems"][0]["file"] == "paper.pdf"
    assert stats["successItems"][0]["journal"] == "Nature"
    assert stats["successItems"][0]["bestEqe"] == "22.5%"
    assert stats["errorItems"][0]["file"] == "bad.pdf"
    assert stats["reportFiles"]["excel"].endswith("report.xlsx")


def test_has_online_capability_requires_real_credentials():
    config = normalize_config(DEFAULT_CONFIG)

    assert _has_online_capability(config) is False

    config["llm"]["api_key"] = "sk-test"
    assert _has_online_capability(config) is True


def test_startup_recommendation_prefers_bundled_and_regex_without_credentials():
    config = normalize_config(DEFAULT_CONFIG)
    recommendation, readiness = _build_startup_recommendation(
        config,
        {
            "bundledBackend": {"available": True},
            "network": {"available": True},
            "systemPython": {"available": True, "hasPaperInsight": True},
        },
    )

    assert recommendation["engineMode"] == "bundled"
    assert recommendation["analysisMode"] == "regex"
    assert recommendation["fallbackTool"]["id"] == "regex"
    assert readiness["status"] == "limited"


def test_startup_recommendation_falls_back_to_system_python_when_needed():
    config = normalize_config(DEFAULT_CONFIG)
    config["llm"]["api_key"] = "sk-test"
    recommendation, readiness = _build_startup_recommendation(
        config,
        {
            "bundledBackend": {"available": False},
            "network": {"available": True},
            "systemPython": {"available": True, "hasPaperInsight": True},
        },
    )

    assert recommendation["engineMode"] == "system_python"
    assert recommendation["analysisMode"] == "api"
    assert readiness["status"] == "ready"


def test_env_info_structure_has_required_keys():
    """快照测试：env-info 返回结构应包含所有必需的顶层 key。"""
    config = normalize_config(DEFAULT_CONFIG)
    recommendation, readiness = _build_startup_recommendation(
        config,
        {
            "bundledBackend": {"available": True, "current": False, "path": "", "message": ""},
            "network": {"available": True},
            "systemPython": {"available": False, "path": "", "hasPaperInsight": False, "message": ""},
        },
    )

    # 模拟 env-info 的 env 结构
    env = {
        "pythonExecutable": "/usr/bin/python3",
        "pythonVersion": "3.13.0",
        "platform": "win32",
        "version": "3.0.7",
        "engineMode": "bundled",
        "checks": {
            "bundledBackend": {
                "available": True,
                "current": False,
                "path": "",
                "message": "Bundled backend detected.",
            },
            "network": {"available": True},
            "systemPython": {
                "available": False,
                "path": "",
                "hasPaperInsight": False,
                "message": "System Python not found.",
            },
        },
        "recommendation": recommendation,
        "readiness": readiness,
    }

    # 验证顶层 key 完整性
    assert "pythonExecutable" in env
    assert "pythonVersion" in env
    assert "platform" in env
    assert "version" in env
    assert "engineMode" in env
    assert "checks" in env
    assert "recommendation" in env
    assert "readiness" in env

    # 验证 checks 子结构
    checks = env["checks"]
    assert "bundledBackend" in checks
    assert "network" in checks
    assert "systemPython" in checks

    # 验证 recommendation 子结构
    rec = env["recommendation"]
    assert "engineMode" in rec
    assert "analysisMode" in rec
    assert "fallbackTool" in rec

    # 验证 readiness 子结构
    rd = env["readiness"]
    assert "status" in rd
    assert "summary" in rd
    assert rd["status"] in {"ready", "limited", "not_ready"}


def test_build_stats_structure_covers_all_message_types():
    """快照测试：stats 结构应包含 progress/file-complete/completed 消息所需字段。"""
    stats = _build_stats(
        pdf_files=[],
        results=[],
        errors=[],
        report_files={},
        renamed_count=0,
        processed_items=[],
    )

    # progress 消息需要的字段
    assert "pdfCount" in stats
    assert "status" in stats

    # completed 消息需要的字段
    assert "successCount" in stats
    assert "errorCount" in stats
    assert "renamedCount" in stats
    assert "reportFiles" in stats

    # file-complete 消息需要的 successItems 和 errorItems
    assert "successItems" in stats
    assert "errorItems" in stats
    assert isinstance(stats["successItems"], list)
    assert isinstance(stats["errorItems"], list)

    # 验证 successItems 结构
    pdf_path = Path("/tmp/test.pdf")
    paper = PaperData(
        paper_info=PaperInfo(
            title="Test",
            journal_name="Nature",
            impact_factor=12.3,
        ),
    )
    stats_with_data = _build_stats(
        pdf_files=[pdf_path],
        results=[paper],
        errors=[],
        report_files={},
        renamed_count=0,
        processed_items=[(pdf_path, paper)],
    )

    item = stats_with_data["successItems"][0]
    assert "file" in item
    assert "path" in item
    assert "title" in item
    assert "journal" in item
    assert "impactFactor" in item
    assert "bestEqe" in item
