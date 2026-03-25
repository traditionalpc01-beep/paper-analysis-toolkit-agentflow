"""
字段映射一致性校验测试 (P0-2.4)

验证 REPORT_COLUMNS 中每个 field_key 都能通过 FIELD_MAPPING 或 to_excel_row() 找到对应值来源，
确保三层映射不会断裂。
"""

import pytest
from paperinsight.models.schemas import PaperData, PaperInfo
from paperinsight.core.reporter import ReportGenerator


class TestFieldMappingConsistency:
    """校验 REPORT_COLUMNS -> FIELD_MAPPING -> to_excel_row 三层映射一致性。"""

    def test_all_report_columns_have_field_mapping(self):
        """REPORT_COLUMNS 中的每个 field_key 都必须在 FIELD_MAPPING 中有定义。"""
        for header, field_key in ReportGenerator.REPORT_COLUMNS:
            assert field_key in ReportGenerator.FIELD_MAPPING, (
                f"REPORT_COLUMNS 中的 field_key '{field_key}' (列: '{header}') "
                f"在 FIELD_MAPPING 中找不到定义"
            )

    def test_field_mapping_aliases_reach_to_excel_row(self):
        """FIELD_MAPPING 中的每个规范化 key 的所有别名，必须至少能在 to_excel_row() 中出现一个。"""
        # 构造一个 PaperData 获取 to_excel_row() 的所有 key
        paper_info = PaperInfo(
            title="Test Title",
            authors="Test Author",
            journal_name="Test Journal",
        )
        paper_data = PaperData(paper_info=paper_info)
        excel_row_keys = set(paper_data.to_excel_row().keys())

        unmapped_keys = []
        for canonical_key, aliases in ReportGenerator.FIELD_MAPPING.items():
            # 检查规范化 key 本身是否在 to_excel_row() 中
            # 或者别名中至少有一个在 to_excel_row() 中
            # 注意：部分 key 如 "file", "url", "processing_status" 是 pipeline 运行时注入的，
            # 不在 to_excel_row() 中，需要跳过
            runtime_only_keys = {"file", "url", "processing_status"}
            if canonical_key in runtime_only_keys:
                continue

            found = False
            for alias in aliases:
                if alias in excel_row_keys:
                    found = True
                    break

            if not found:
                unmapped_keys.append(canonical_key)

        assert not unmapped_keys, (
            f"以下 FIELD_MAPPING key 的所有别名都无法在 to_excel_row() 中找到: {unmapped_keys}"
        )

    def test_no_duplicate_field_keys_in_report_columns(self):
        """REPORT_COLUMNS 中的 field_key 不应重复。"""
        field_keys = [fk for _, fk in ReportGenerator.REPORT_COLUMNS]
        assert len(field_keys) == len(set(field_keys)), (
            f"REPORT_COLUMNS 中存在重复的 field_key: "
            f"{[k for k in field_keys if field_keys.count(k) > 1]}"
        )

    def test_empty_result_row_matches_report_columns(self):
        """empty_result_row() 返回的字典 key 必须与 REPORT_COLUMNS 的 field_key 完全一致。"""
        row = ReportGenerator.empty_result_row()
        report_field_keys = [fk for _, fk in ReportGenerator.REPORT_COLUMNS]
        row_keys = list(row.keys())

        # empty_result_row 应包含所有 REPORT_COLUMNS 的 field_key
        missing_in_row = set(report_field_keys) - set(row_keys)
        extra_in_row = set(row_keys) - set(report_field_keys)

        assert not missing_in_row, (
            f"empty_result_row() 缺少以下 REPORT_COLUMNS field_key: {missing_in_row}"
        )
        assert not extra_in_row, (
            f"empty_result_row() 包含多余的 key: {extra_in_row}"
        )

    def test_to_excel_row_has_no_empty_none_values_for_basic_fields(self):
        """to_excel_row() 中核心字段不应返回空值（当 PaperData 有合理数据时）。"""
        paper_info = PaperInfo(
            title="Test Paper",
            authors="Author A, Author B",
            journal_name="Nature Photonics",
            impact_factor=32.5,
            impact_factor_year=2024,
            impact_factor_source="MJL_PROFILE_API",
            impact_factor_status="OK",
        )
        paper_data = PaperData(paper_info=paper_info)
        row = paper_data.to_excel_row()

        # 核心字段应有值
        assert row["标题"] == "Test Paper"
        assert row["作者"] == "Author A, Author B"
        assert row["期刊"] == "Nature Photonics"
        assert row["影响因子"] == 32.5
        assert row["影响因子年份"] == 2024
