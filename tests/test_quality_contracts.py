from paperinsight.core.reporter import ReportGenerator
from paperinsight.utils.config import DEFAULT_CONFIG, normalize_config


def test_report_columns_keep_expected_field_order():
    fields = [field for _, field in ReportGenerator.REPORT_COLUMNS]

    assert fields == [
        "file",
        "url",
        "journal",
        "impact_factor",
        "impact_factor_year",
        "impact_factor_source",
        "impact_factor_status",
        "authors",
        "processing_status",
        "title",
        "structure",
        "eqe",
        "cie",
        "lifetime",
        "best_eqe",
        "optimization_level",
        "optimization_strategy",
        "optimization_details",
        "key_findings",
        "eqe_source",
        "cie_source",
        "lifetime_source",
        "structure_source",
    ]


def test_report_columns_keep_expected_count():
    assert len(ReportGenerator.REPORT_COLUMNS) == 23


def test_reporter_default_filename_uses_chinese_prefix(tmp_path):
    reporter = ReportGenerator(tmp_path)

    path = reporter.generate_excel_report([])

    assert path.name.startswith("论文分析报告_")
    assert path.suffix == ".xlsx"


def test_default_config_keeps_agent_first_baseline_defaults():
    config = normalize_config(DEFAULT_CONFIG)

    assert set(config) >= {
        "mineru",
        "paddlex",
        "llm",
        "web_search",
        "cache",
        "output",
        "pdf",
        "cleaner",
        "desktop",
    }
    assert config["mineru"]["mode"] == "api"
    assert config["output"]["format"] == ["excel"]
    assert config["llm"]["provider"] == "longcat"
    assert config["desktop"]["engine"]["mode"] == "bundled"
