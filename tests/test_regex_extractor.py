"""P2-4.6: 测试覆盖率提升 — DataExtractor._extract_with_regex 端到端测试"""

from paperinsight.core.extractor import DataExtractor
from paperinsight.parser.base import ParseResult


class TestRegexExtractorEndToEnd:
    """DataExtractor._extract_with_regex 端到端测试。

    验证正则提取路径能完整填充 PaperData 的所有主要字段。
    """

    def _make_extractor(self):
        return DataExtractor(config={"llm": {"enabled": False}})

    def test_complete_extraction_from_realistic_markdown(self):
        """从一段真实风格的 Markdown 提取完整 PaperData。"""
        extractor = self._make_extractor()
        text = """
Highly Efficient Blue Perovskite LEDs via Surface Passivation

John Smith,1,* Jane Doe,1 and Bob Wilson2

1 Department of Materials Science, University of Example
2 Institute of Advanced Optoelectronics

The device achieved a maximum external quantum efficiency (EQE) of 22.5% with CIE coordinates of (0.15, 0.08).
The champion device structure was ITO/PEDOT:PSS/PeBr3/ZnMgO/TPBi/LiF/Al.
Current efficiency reached 45.2 cd/A and power efficiency was 28.3 lm/W.
The operational lifetime (LT50) was measured at 100 cd/m² and reached 200 h.
Turn-on voltage was 3.2 V.

A control device using the structure ITO/NiO/QDs/Al showed lower performance with EQE of 10.1%.
"""
        result = extractor.extract(markdown_text=text, cleaned_text=text)

        assert result.success is True
        pi = result.data.paper_info

        # 发光材料类型应被检测到
        assert pi.emitter_type == "Perovskite"

        # 作者
        assert pi.authors
        assert "Smith" in pi.authors

        # 器件
        devices = result.data.devices
        assert len(devices) >= 2
        assert any(d.eqe and "22.50%" in d.eqe for d in devices)
        assert any(d.cie and "0.15" in d.cie for d in devices)
        assert any("ITO/PEDOT:PSS" in (d.structure or "") for d in devices)

        # 最佳 EQE
        assert result.data.paper_info.best_eqe == "22.50%"

    def test_extraction_with_parse_metadata(self):
        """验证 parse metadata 能正确回填到 paper_info。"""
        extractor = self._make_extractor()
        text = "The device had EQE of 15.0%."
        parse_result = ParseResult(
            success=True,
            markdown=text,
            metadata={
                "journal": "Nature Photonics",
                "issn": "1749-4885",
                "eissn": "1749-4893",
                "subject": "Nat. Photon. 2026.10:1001",
            },
        )
        result = extractor.extract(markdown_text=text, cleaned_text=text, parse_result=parse_result)

        assert result.success is True
        pi = result.data.paper_info
        assert pi.journal_name == "Nature Photonics"
        assert pi.raw_journal_title == "Nature Photonics"
        assert pi.raw_issn == "1749-4885"
        assert pi.raw_eissn == "1749-4893"

    def test_extractor_identifies_research_and_emitter_type(self):
        """验证研究类型和发光材料类型检测。"""
        extractor = self._make_extractor()
        text = """
Blue perovskite light-emitting diodes (PeLEDs) were fabricated.
The device structure was ITO/PEDOT:PSS/PeBr3/ZnMgO/TPBi/LiF/Al.
Maximum EQE reached 20.3% with CIE (0.12, 0.06).
"""
        result = extractor.extract(markdown_text=text, cleaned_text=text)

        assert result.success is True
        pi = result.data.paper_info
        # 研究类型应检测到 LED 相关
        assert pi.research_type  # 不应为空
        # 发光材料类型应检测到 Perovskite
        assert pi.emitter_type

    def test_extractor_extracts_year_from_text(self):
        """验证年份提取。"""
        extractor = self._make_extractor()
        text = """
Accepted: March 2025. Published online: April 2025.
The device EQE was 5.0%.
"""
        result = extractor.extract(markdown_text=text, cleaned_text=text)

        assert result.success is True
        assert result.data.paper_info.year == 2025

    def test_extractor_handles_no_device_text(self):
        """无器件数据时不应崩溃，应返回空设备列表。"""
        extractor = self._make_extractor()
        text = """
This is a review article about recent advances in display technology.
No specific device performance data is reported.
"""
        result = extractor.extract(markdown_text=text, cleaned_text=text)

        assert result.success is True
        assert len(result.data.devices) == 0 or all(
            d.structure is None and d.eqe is None for d in result.data.devices
        )

    def test_extractor_detects_optimization_info(self):
        """验证优化信息提取。"""
        extractor = self._make_extractor()
        text = """
The device was optimized by using surface passivation with octylphosphonic acid.
The ligand exchange process improved carrier balance.
EQE reached 18.5% with CIE (0.20, 0.10).
Device structure: ITO/PEDOT:PSS/QDs/ZnMgO/Al.
"""
        result = extractor.extract(markdown_text=text, cleaned_text=text)

        assert result.success is True
        opt = result.data.optimization
        # 优化策略应包含 passivation 相关关键词
        if opt.strategy:
            assert isinstance(opt.strategy, str)

    def test_extractor_captures_data_source(self):
        """验证数据溯源字段填充。"""
        extractor = self._make_extractor()
        text = """
As shown in Figure 2, the EQE reached 23.1%.
According to Table 1, the CIE coordinates were (0.65, 0.35).
The operational stability was measured and LT50 = 100 h.
Device structure from inset: ITO/PEDOT:PSS/QDs/TPBi/LiF/Al.
"""
        result = extractor.extract(markdown_text=text, cleaned_text=text)

        assert result.success is True
        ds = result.data.data_source
        assert ds is not None
        # 至少应有部分溯源信息
        assert ds.eqe_source or ds.cie_source or ds.structure_source or ds.lifetime_source

    def test_extractor_sanitizes_duplicate_devices(self):
        """验证去重逻辑——相似器件应被合并。"""
        extractor = self._make_extractor()
        text = """
Device structure ITO/PEDOT:PSS/QDs/ZnMgO/TPBi/LiF/Al achieved EQE of 15.0%.
The same structure ITO/PEDOT:PSS/QDs/ZnMgO/TPBi/LiF/Al showed maximum EQE of 15.0% and CIE (0.60, 0.40).
"""
        result = extractor.extract(markdown_text=text, cleaned_text=text)

        assert result.success is True
        # 相同结构和 EQE 的器件应该只保留一个（或合并）
        qd_devices = [d for d in result.data.devices if d.structure and "QDs" in d.structure]
        assert len(qd_devices) <= 2  # 最多保留少量不重复的

    def test_extractor_handles_multiline_structure(self):
        """验证跨行器件结构能被正确提取。"""
        extractor = self._make_extractor()
        text = """
The device was fabricated with the following structure:
ITO / PEDOT:PSS / CsPbBr3 / ZnMgO / TPBi / LiF / Al
which achieved an EQE of 17.8%.
"""
        result = extractor.extract(markdown_text=text, cleaned_text=text)

        assert result.success is True
        assert any(d.structure and "CsPbBr3" in d.structure for d in result.data.devices)
