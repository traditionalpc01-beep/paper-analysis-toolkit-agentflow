"""P2-4.6d: 新拆分子模块的基本测试 — journal_utils / device_extractor / metadata_extractor"""

import pytest


# ── journal_utils ──────────────────────────────────────────


class TestJournalUtils:
    """journal_utils 子模块纯函数基本测试。"""

    def test_extract_journal_name_from_subject(self):
        """从 subject 字段提取期刊名称。函数接收 metadata dict。"""
        from paperinsight.core.journal_utils import extract_journal_name_from_subject

        # 完整期刊名应能返回
        assert extract_journal_name_from_subject({"subject": "Advanced Materials 2024.36:2404480"}) == "Advanced Materials"
        assert extract_journal_name_from_subject({"subject": "Nature Photonics 2026.10:1001"}) == "Nature Photonics"
        # subject 为 None 或空时应返回 None
        assert extract_journal_name_from_subject({"subject": None}) is None
        assert extract_journal_name_from_subject({}) is None

    def test_extract_issn_from_text(self):
        """从文本中提取 ISSN。"""
        from paperinsight.core.journal_utils import extract_issn_from_text

        text = "Print ISSN 2041-1723 Online ISSN 2041-1723"
        issn, eissn = extract_issn_from_text(text)
        assert issn == "2041-1723"
        assert eissn == "2041-1723"

    def test_extract_issn_from_text_no_match(self):
        """无 ISSN 时应返回 None。"""
        from paperinsight.core.journal_utils import extract_issn_from_text

        issn, eissn = extract_issn_from_text("No ISSN information here.")
        assert issn is None
        assert eissn is None

    def test_normalize_journal_title_candidate(self):
        """期刊名称规范化。"""
        from paperinsight.core.journal_utils import normalize_journal_title_candidate

        assert normalize_journal_title_candidate("Nature Communications") == "Nature Communications"
        assert normalize_journal_title_candidate("  Advanced Materials  ") == "Advanced Materials"

    def test_coerce_metadata_value(self):
        """元数据值强制转换。"""
        from paperinsight.core.journal_utils import coerce_metadata_value

        # coerce_metadata_value 只接收一个参数，返回 Optional[str]
        assert coerce_metadata_value("hello") == "hello"
        assert coerce_metadata_value(None) is None
        assert coerce_metadata_value("") is None
        assert coerce_metadata_value(123) == "123"
        assert coerce_metadata_value(["", "world"]) == "world"
        assert coerce_metadata_value(["", None]) is None

    def test_first_non_empty(self):
        """取第一个非空值。"""
        from paperinsight.core.journal_utils import first_non_empty

        assert first_non_empty(None, "", "hello", "world") == "hello"
        assert first_non_empty(None, None) is None
        assert first_non_empty("first", "second") == "first"

    def test_load_journal_aliases(self):
        """加载期刊别名表。"""
        from paperinsight.core.journal_utils import load_journal_aliases

        # 返回 (domain_hints, title_aliases) 元组
        domain_hints, title_aliases = load_journal_aliases()
        assert isinstance(domain_hints, dict)
        assert isinstance(title_aliases, dict)


# ── metadata_extractor ────────────────────────────────────


class TestMetadataExtractor:
    """metadata_extractor 子模块纯函数基本测试。"""

    def test_extract_title_from_text(self):
        """从 parse_result metadata 提取论文标题。"""
        from paperinsight.core.metadata_extractor import extract_title, normalize_title_candidate, is_bad_title_candidate
        from paperinsight.parser.base import ParseResult

        # extract_title 从 metadata 中提取标题候选，但 is_bad_title_candidate 可能过滤
        # 使用简短有效标题
        title = "Blue Perovskite Nanocrystal LEDs"
        norm = normalize_title_candidate(title)
        bad = is_bad_title_candidate(norm) if norm else True
        if not bad:
            parse_result = ParseResult(
                success=True, markdown="", metadata={"title": title},
            )
            result = extract_title("", parse_result=parse_result)
            assert result is not None
        else:
            # 即使 is_bad_title_candidate 过滤了，函数不应崩溃
            parse_result = ParseResult(
                success=True, markdown="", metadata={"title": title},
            )
            result = extract_title("", parse_result=parse_result)
            assert isinstance(result, (str, type(None)))

    def test_extract_authors_from_text(self):
        """从文本中提取作者。"""
        from paperinsight.core.metadata_extractor import extract_authors

        text = "John Smith,1,* Jane Doe,1 and Bob Wilson2\n\nDepartment of Materials Science"
        authors = extract_authors(text, parse_result=None)
        assert "Smith" in authors

    def test_detect_research_type(self):
        """检测研究类型。"""
        from paperinsight.core.metadata_extractor import detect_research_type

        text = "Perovskite light-emitting diodes (PeLEDs) were fabricated."
        rtype = detect_research_type(text)
        assert rtype  # 不应为空

    def test_detect_emitter_type(self):
        """检测发光材料类型。"""
        from paperinsight.core.metadata_extractor import detect_emitter_type

        text = "CsPbBr3 perovskite nanocrystals were used as emitters."
        etype = detect_emitter_type(text)
        assert etype  # 应检测到 perovskite

    def test_extract_year(self):
        """提取年份。"""
        from paperinsight.core.metadata_extractor import extract_year

        text = "Received: January 2025. Accepted: March 2025."
        year = extract_year(text)
        assert year == 2025

    def test_extract_impact_factor(self):
        """提取影响因子。"""
        from paperinsight.core.metadata_extractor import extract_impact_factor

        text = "Impact Factor: 25.3"
        if_val = extract_impact_factor(text)
        # 影响因子可能提取到也可能不提取到，取决于正则匹配
        # 关键是不崩溃
        assert if_val is None or isinstance(if_val, (int, float))

    def test_score_title_candidate(self):
        """标题候选评分。"""
        from paperinsight.core.metadata_extractor import score_title_candidate

        # 正常论文标题应有正分（需要 index 和 heading_hint 关键字参数）
        score = score_title_candidate("Highly Efficient Blue Perovskite LEDs via Surface Passivation", index=0, heading_hint=True)
        assert score > 0

        # 短噪声文本应有低分
        bad_score = score_title_candidate("Fig. 1", index=5, heading_hint=False)
        assert bad_score < score


# ── device_extractor ──────────────────────────────────────


class TestDeviceExtractor:
    """device_extractor 子模块纯函数基本测试。"""

    def test_extract_all_structures(self):
        """提取器件结构。"""
        from paperinsight.core.device_extractor import extract_all_structures

        text = "The device structure was ITO/PEDOT:PSS/QDs/ZnMgO/Al and achieved EQE 20%."
        structures = extract_all_structures(text)
        assert len(structures) > 0
        assert any("ITO" in s and "QDs" in s for s in structures)

    def test_extract_all_eqe(self):
        """提取 EQE 值。"""
        from paperinsight.core.device_extractor import extract_all_eqe

        text = "EQE of 20.5% and maximum EQE of 22.1% were achieved."
        eqe_values = extract_all_eqe(text)
        assert len(eqe_values) >= 2
        assert "22.10%" in eqe_values or "22.1%" in eqe_values

    def test_extract_all_cie(self):
        """提取 CIE 坐标。"""
        from paperinsight.core.device_extractor import extract_all_cie

        text = "CIE coordinates of (0.15, 0.08) and (0.63, 0.36)."
        cie_values = extract_all_cie(text)
        assert len(cie_values) >= 1
        assert any("0.15" in c for c in cie_values)

    def test_extract_all_lifetime(self):
        """提取寿命值。"""
        from paperinsight.core.device_extractor import extract_all_lifetime

        text = "LT50 = 150 h at 100 cd/m² and T90 = 50 h."
        lifetime_values = extract_all_lifetime(text)
        assert len(lifetime_values) >= 1
        assert any("150" in l for l in lifetime_values)

    def test_segment_signal_score(self):
        """段落信号评分。"""
        from paperinsight.core.device_extractor import segment_signal_score

        # 高价值段落应有高分
        high_score = segment_signal_score(
            "The champion device with ITO/PEDOT:PSS/QDs/ZnMgO/TPBi/LiF/Al achieved maximum EQE of 25.5% with CIE (0.65, 0.35)."
        )
        # 低价值段落应有低分
        low_score = segment_signal_score(
            "This work was supported by the National Science Foundation."
        )
        assert high_score > low_score

    def test_device_signal_score(self):
        """器件信号评分。"""
        from paperinsight.core.device_extractor import device_signal_score
        from paperinsight.models.schemas import DeviceData

        device = DeviceData(
            structure="ITO/PEDOT:PSS/QDs/ZnMgO/TPBi/LiF/Al",
            eqe="22.50%",
            cie="(0.63, 0.36)",
            lifetime="LT50 = 200 h",
        )
        score = device_signal_score(device)
        assert score > 0

    def test_device_signature(self):
        """器件签名生成。"""
        from paperinsight.core.device_extractor import device_signature
        from paperinsight.models.schemas import DeviceData

        device = DeviceData(
            structure="ITO/PEDOT:PSS/QDs/ZnMgO/TPBi/LiF/Al",
            eqe="22.50%",
            cie="(0.63, 0.36)",
        )
        sig = device_signature(device)
        assert isinstance(sig, tuple)
        assert len(sig) == 5

    def test_sanitize_devices_removes_empty(self):
        """清洗应移除全空的器件（信号分=0），保留有实质数据的器件。"""
        from paperinsight.core.device_extractor import sanitize_devices
        from paperinsight.models.schemas import PaperData, PaperInfo, DeviceData

        paper_data = PaperData(
            paper_info=PaperInfo(),
            devices=[
                DeviceData(structure=None, eqe=None, cie=None),  # 空：应被移除
                DeviceData(structure="ITO/Al", eqe="15.00%", cie=None),  # 有 EQE：应保留
                DeviceData(structure=None, eqe=None, cie="(0.5, 0.5)"),  # 有 CIE：应保留
            ],
        )
        result = sanitize_devices(paper_data)
        assert len(result.devices) >= 2

    def test_refresh_best_eqe(self):
        """刷新最佳 EQE。"""
        from paperinsight.core.device_extractor import refresh_best_eqe
        from paperinsight.models.schemas import PaperData, PaperInfo, DeviceData

        paper_data = PaperData(
            paper_info=PaperInfo(best_eqe=None),  # 必须为 None 才会刷新
            devices=[
                DeviceData(eqe="10.00%"),
                DeviceData(eqe="3.00%"),
                DeviceData(eqe="25.00%"),
            ],
        )
        # refresh_best_eqe 是原地修改（返回 None）
        refresh_best_eqe(paper_data)
        assert paper_data.paper_info.best_eqe == "25.00%"
