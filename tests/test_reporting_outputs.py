import openpyxl

from paperinsight.core.reporter import ReportGenerator
from paperinsight.models.schemas import PaperData, PaperInfo


def test_report_generator_uses_bilingual_headers_and_unique_filename(tmp_path):
    reporter = ReportGenerator(tmp_path)
    results = [
        {
            "File": "paper.pdf",
            "URL": "file:///tmp/paper.pdf",
            "期刊": "Nature",
            "影响因子": 12.3,
            "作者": "Alice",
            "处理结果/简述": "处理成功：结构完整",
            "标题": "中文：示例标题\nEnglish: Sample Title",
            "器件结构": "ITO/EML/Al",
            "EQE": "20.5%",
            "CIE": "(0.21, 0.32)",
            "寿命": "120 h",
            "最高EQE": "20.5%",
            "优化层级": "界面工程",
            "优化策略": "中文：中文总结\nEnglish: English summary",
        }
    ]

    first_path = reporter.generate_excel_report(results)
    second_path = reporter.generate_excel_report(results)

    assert first_path.name.startswith("论文分析报告_")
    assert second_path.name.startswith("论文分析报告_")
    assert first_path != second_path

    workbook = openpyxl.load_workbook(first_path)
    sheet = workbook.active
    headers = [sheet.cell(row=1, column=idx).value for idx in range(1, 12)]
    values = [sheet.cell(row=2, column=idx).value for idx in range(1, 12)]

    assert headers == [
        "文件名 File",
        "文件地址 URL",
        "期刊名称 Journal",
        "影响因子 Impact Factor",
        "影响因子年份 IF Year",
        "影响因子来源 IF Source",
        "影响因子状态 IF Status",
        "作者 Authors",
        "处理结果/简述 Processing Status",
        "论文标题 Title",
        "器件结构 Device Structure",
    ]
    assert values == [
        "paper.pdf",
        "file:///tmp/paper.pdf",
        "Nature",
        12.3,
        None,
        None,
        None,
        "Alice",
        "处理成功：结构完整",
        "中文：示例标题\nEnglish: Sample Title",
        "ITO/EML/Al",
    ]

    all_headers = [sheet.cell(row=1, column=idx).value for idx in range(1, sheet.max_column + 1)]
    assert "原始期刊标题 Raw Journal" not in all_headers
    assert "原始ISSN Raw ISSN" not in all_headers
    assert "原始eISSN Raw eISSN" not in all_headers
    assert "匹配期刊 Matched Journal" not in all_headers
    assert "匹配ISSN Matched ISSN" not in all_headers
    assert "匹配方式 Match Method" not in all_headers
    assert "期刊主页 Journal Profile URL" not in all_headers
    assert "影响因子年份 IF Year" in all_headers
    assert "影响因子来源 IF Source" in all_headers
    assert "影响因子状态 IF Status" in all_headers


def test_paper_data_to_excel_row_includes_journal_enrichment_fields():
    paper_data = PaperData(
        paper_info=PaperInfo(
            journal_name="Nature",
            raw_journal_title="NATURE",
            raw_issn="1476-4687",
            raw_eissn="1476-4687",
            matched_journal_title="Nature",
            matched_issn="1476-4687",
            match_method="issn",
            journal_profile_url="https://example.test/journal/nature",
            impact_factor=12.3,
            impact_factor_year=2025,
            impact_factor_source="MJL_WEB",
            impact_factor_status="OK",
        )
    )

    row = paper_data.to_excel_row()

    assert row["期刊"] == "Nature"
    assert row["原始期刊标题"] == "NATURE"
    assert row["原始ISSN"] == "1476-4687"
    assert row["原始eISSN"] == "1476-4687"
    assert row["匹配期刊"] == "Nature"
    assert row["匹配ISSN"] == "1476-4687"
    assert row["匹配方式"] == "issn"
    assert row["期刊主页"] == "https://example.test/journal/nature"
    assert row["影响因子年份"] == 2025
    assert row["影响因子来源"] == "MJL_WEB"
    assert row["影响因子状态"] == "OK"


def test_report_generator_highlights_rows_with_many_missing_fields(tmp_path):
    reporter = ReportGenerator(tmp_path)
    results = [
        {
            "File": "bad.pdf",
            "URL": "file:///tmp/bad.pdf",
            "处理结果/简述": "处理失败：数据提取 - 返回空结果",
            "标题": "",
            "期刊": "",
            "影响因子": "",
            "作者": "",
            "器件结构": "",
            "EQE": "",
            "CIE": "",
            "寿命": "",
            "最高EQE": "",
            "优化策略": "",
        }
    ]

    path = reporter.generate_excel_report(results)
    workbook = openpyxl.load_workbook(path)
    sheet = workbook.active
    assert sheet["A2"].fill.start_color.rgb in {"00FFF9EF", "FFFFF9EF"}


def test_report_generator_keeps_if_audit_fields_when_value_is_empty(tmp_path):
    reporter = ReportGenerator(tmp_path)
    results = [
        {
            "File": "nature.pdf",
            "URL": "file:///tmp/nature.pdf",
            "期刊": "Nature",
            "影响因子": "",
            "影响因子年份": "",
            "影响因子来源": "MJL_PROFILE_API",
            "影响因子状态": "NO_ACCESS",
        }
    ]

    path = reporter.generate_excel_report(results)
    workbook = openpyxl.load_workbook(path)
    sheet = workbook.active

    assert sheet["D2"].value is None
    assert sheet["E2"].value is None
    assert sheet["F2"].value == "MJL_PROFILE_API"
    assert sheet["G2"].value == "NO_ACCESS"


def test_report_exports_not_visible_no_match_error_statuses(tmp_path):
    """NOT_VISIBLE/NO_MATCH/ERROR 状态的 IF 审计字段应完整出现在 Excel 中。"""
    reporter = ReportGenerator(tmp_path)
    results = [
        {
            "File": "a.pdf",
            "URL": "file:///tmp/a.pdf",
            "期刊": "Journal A",
            "影响因子": "",
            "影响因子年份": "",
            "影响因子来源": "MJL_PROFILE_API",
            "影响因子状态": "NOT_VISIBLE",
        },
        {
            "File": "b.pdf",
            "URL": "file:///tmp/b.pdf",
            "期刊": "Journal B",
            "影响因子": "",
            "影响因子年份": "",
            "影响因子来源": "CURATED_FALLBACK",
            "影响因子状态": "NO_MATCH",
        },
        {
            "File": "c.pdf",
            "URL": "file:///tmp/c.pdf",
            "期刊": "Journal C",
            "影响因子": "",
            "影响因子年份": "",
            "影响因子来源": "SEARCH_CRAWLER",
            "影响因子状态": "ERROR",
        },
    ]

    path = reporter.generate_excel_report(results)
    workbook = openpyxl.load_workbook(path)
    sheet = workbook.active

    # Row 2: NOT_VISIBLE
    assert sheet.cell(row=2, column=4).value is None  # IF value empty
    assert sheet.cell(row=2, column=6).value == "MJL_PROFILE_API"
    assert sheet.cell(row=2, column=7).value == "NOT_VISIBLE"

    # Row 3: NO_MATCH
    assert sheet.cell(row=3, column=6).value == "CURATED_FALLBACK"
    assert sheet.cell(row=3, column=7).value == "NO_MATCH"

    # Row 4: ERROR
    assert sheet.cell(row=4, column=6).value == "SEARCH_CRAWLER"
    assert sheet.cell(row=4, column=7).value == "ERROR"


def test_report_exports_ok_stale_if_status(tmp_path):
    """OK_STALE 状态的 IF 审计字段应完整出现在 Excel 中。"""
    reporter = ReportGenerator(tmp_path)
    results = [
        {
            "File": "stale.pdf",
            "URL": "file:///tmp/stale.pdf",
            "期刊": "Old Journal",
            "影响因子": 5.0,
            "影响因子年份": 2022,
            "影响因子来源": "CURATED_FALLBACK",
            "影响因子状态": "OK_STALE",
        },
    ]

    path = reporter.generate_excel_report(results)
    workbook = openpyxl.load_workbook(path)
    sheet = workbook.active

    assert sheet.cell(row=2, column=4).value == 5.0
    assert sheet.cell(row=2, column=5).value == 2022
    assert sheet.cell(row=2, column=6).value == "CURATED_FALLBACK"
    assert sheet.cell(row=2, column=7).value == "OK_STALE"


def test_to_excel_row_includes_optimization_level():
    """optimization_level 应出现在 to_excel_row 输出中。"""
    from paperinsight.models.schemas import OptimizationInfo

    paper_data = PaperData(
        paper_info=PaperInfo(title="Test"),
        optimization=OptimizationInfo(level="界面工程", strategy="HIL/ETL modification"),
    )
    row = paper_data.to_excel_row()
    assert row["优化层级"] == "界面工程"


def test_to_excel_row_optimization_level_is_none_when_absent():
    """没有 optimization 时优化层级应为 None。"""
    paper_data = PaperData(paper_info=PaperInfo(title="Test"))
    row = paper_data.to_excel_row()
    assert row["优化层级"] is None


def test_pipeline_error_row_includes_if_audit_columns(tmp_path):
    """Pipeline 错误行的 Excel 输出应包含 IF 审计列（年份/来源/状态）。"""
    from paperinsight.core.pipeline import AnalysisPipeline

    pipeline = AnalysisPipeline(
        output_dir=tmp_path,
        config={
            "cache": {"enabled": False},
            "mineru": {"enabled": False},
            "llm": {"enabled": False},
            "web_search": {"enabled": False},
            "output": {"format": ["excel"]},
        },
    )

    import tempfile
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()

    stats = pipeline.run(pdf_dir=pdf_dir)
    assert stats["status"] == "no_files"
    assert stats["pdf_count"] == 0
