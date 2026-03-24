"""
Pydantic 数据模型定义

根据 PRD v3.0 规范，定义论文数据提取的结构化模型。
实现嵌套式 JSON Schema，确保实验参数与器件结构强绑定。
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict
import re


class DataSourceReference(BaseModel):
    """数据溯源引用 - 记录参数来源的原文句子"""
    
    model_config = ConfigDict(extra='forbid')
    
    eqe_source: Optional[str] = Field(
        default=None, 
        description="EQE 数据的原文引用句子"
    )
    cie_source: Optional[str] = Field(
        default=None, 
        description="CIE 数据的原文引用句子"
    )
    lifetime_source: Optional[str] = Field(
        default=None, 
        description="寿命数据的原文引用句子"
    )
    structure_source: Optional[str] = Field(
        default=None, 
        description="器件结构的原文引用句子"
    )


class DeviceData(BaseModel):
    """
    单个器件数据模型
    
    每个器件包含完整的结构参数和性能指标，
    确保数据完整性，避免跨器件数据错位。
    """
    
    model_config = ConfigDict(extra='forbid')
    
    device_label: Optional[str] = Field(
        default=None,
        description="器件标签，如 'Control', 'Champion', 'Device A' 等"
    )
    
    structure: Optional[str] = Field(
        default=None,
        description="完整的器件结构，如 'ITO/PEDOT:PSS/EML/TPBi/LiF/Al'"
    )
    
    eqe: Optional[str] = Field(
        default=None,
        description="外量子效率，如 '22.5%' 或 '18.2% (max)'"
    )
    
    cie: Optional[str] = Field(
        default=None,
        description="CIE 色坐标，如 '(0.21, 0.32)'"
    )
    
    lifetime: Optional[str] = Field(
        default=None,
        description="器件寿命，如 '150 h @ 1000 cd/m²' 或 'LT50 = 200 h'"
    )
    
    luminance: Optional[str] = Field(
        default=None,
        description="亮度数据，如 '5000 cd/m²'"
    )
    
    current_efficiency: Optional[str] = Field(
        default=None,
        description="电流效率，如 '68 cd/A'"
    )
    
    power_efficiency: Optional[str] = Field(
        default=None,
        description="功率效率，如 '45 lm/W'"
    )
    
    notes: Optional[str] = Field(
        default=None,
        description="其他重要备注或实验条件"
    )
    
    @field_validator('eqe', 'cie', 'lifetime', 'structure')
    @classmethod
    def clean_string(cls, v: Optional[str]) -> Optional[str]:
        """清理字符串，移除多余空白"""
        if v is None:
            return v
        # 移除首尾空白，压缩连续空白
        return re.sub(r'\s+', ' ', v.strip())


class OptimizationInfo(BaseModel):
    """优化策略信息"""
    
    model_config = ConfigDict(extra='forbid')
    
    level: Optional[str] = Field(
        default=None,
        description="优化层面，如 '材料合成', '界面工程', '器件结构' 等"
    )
    
    strategy: Optional[str] = Field(
        default=None,
        description="具体优化策略描述"
    )
    
    key_findings: Optional[str] = Field(
        default=None,
        description="关键发现或创新点"
    )


class PaperInfo(BaseModel):
    """
    论文基本信息
    
    包含论文的基本元数据和整体优化策略总结。
    """
    
    model_config = ConfigDict(extra='forbid')
    
    title: Optional[str] = Field(
        default=None,
        description="论文标题"
    )
    
    authors: Optional[str] = Field(
        default=None,
        description="作者列表，逗号分隔"
    )
    
    journal_name: Optional[str] = Field(
        default=None,
        description="期刊名称"
    )

    raw_journal_title: Optional[str] = Field(
        default=None,
        description="期刊原始标题"
    )

    raw_issn: Optional[str] = Field(
        default=None,
        description="原始 print ISSN"
    )

    raw_eissn: Optional[str] = Field(
        default=None,
        description="原始 electronic ISSN"
    )

    matched_journal_title: Optional[str] = Field(
        default=None,
        description="期刊匹配后的标准标题"
    )

    matched_issn: Optional[str] = Field(
        default=None,
        description="期刊匹配后的标准 ISSN"
    )

    match_method: Optional[str] = Field(
        default=None,
        description="期刊匹配方式"
    )

    journal_profile_url: Optional[str] = Field(
        default=None,
        description="期刊主页 URL"
    )

    impact_factor: Optional[float] = Field(
        default=None,
        description="影响因子"
    )

    impact_factor_year: Optional[int] = Field(
        default=None,
        description="影响因子年份"
    )

    impact_factor_source: Optional[str] = Field(
        default=None,
        description="影响因子来源"
    )

    impact_factor_status: Optional[str] = Field(
        default=None,
        description="影响因子获取状态"
    )
    
    year: Optional[int] = Field(
        default=None,
        description="发表年份"
    )
    
    optimization_strategy: Optional[str] = Field(
        default=None,
        description="论文的主要优化策略总结（一句话）"
    )
    
    best_eqe: Optional[str] = Field(
        default=None,
        description="论文报道的最高 EQE 值"
    )
    
    research_type: Optional[str] = Field(
        default=None,
        description="研究类型，如 'OLED', 'PLED', 'QLED', 'PeLED' 等"
    )
    
    emitter_type: Optional[str] = Field(
        default=None,
        description="发光材料类型，如 'TADF', 'Phosphorescent', 'Fluorescent' 等"
    )


class PaperData(BaseModel):
    """
    完整的论文数据模型
    
    按照 v3.0 PRD 规范，实现嵌套式 JSON Schema：
    - paper_info: 论文基本信息
    - devices: 器件数据列表（支持多器件）
    - data_source: 数据溯源引用
    - optimization: 优化策略详情
    """
    
    model_config = ConfigDict(extra='forbid')
    
    paper_info: PaperInfo = Field(
        default_factory=PaperInfo,
        description="论文基本信息"
    )
    
    devices: List[DeviceData] = Field(
        default_factory=list,
        description="器件数据列表，每个元素代表一个完整器件的数据"
    )
    
    data_source: DataSourceReference = Field(
        default_factory=DataSourceReference,
        description="数据溯源引用"
    )
    
    optimization: Optional[OptimizationInfo] = Field(
        default=None,
        description="优化策略详细信息"
    )
    
    def to_excel_row(self) -> Dict[str, Any]:
        """
        转换为 Excel 行数据格式
        
        按照 PRD 要求：
        - 主信息列独占单元格
        - 多器件数据使用 \\n 换行拼接
        """
        # 提取所有器件的数据
        structures = []
        eqes = []
        cies = []
        lifetimes = []
        
        for device in self.devices:
            if device.structure:
                label = f"[{device.device_label}] " if device.device_label else ""
                structures.append(f"{label}{device.structure}")
            if device.eqe:
                label = f"[{device.device_label}] " if device.device_label else ""
                eqes.append(f"{label}{device.eqe}")
            if device.cie:
                label = f"[{device.device_label}] " if device.device_label else ""
                cies.append(f"{label}{device.cie}")
            if device.lifetime:
                label = f"[{device.device_label}] " if device.device_label else ""
                lifetimes.append(f"{label}{device.lifetime}")
        
        journal_display_name = (
            self.paper_info.journal_name
            or self.paper_info.matched_journal_title
            or self.paper_info.raw_journal_title
        )

        return {
            "标题": self.paper_info.title,
            "作者": self.paper_info.authors,
            "期刊": journal_display_name,
            "原始期刊标题": self.paper_info.raw_journal_title,
            "原始ISSN": self.paper_info.raw_issn,
            "原始eISSN": self.paper_info.raw_eissn,
            "匹配期刊": self.paper_info.matched_journal_title,
            "匹配ISSN": self.paper_info.matched_issn,
            "匹配方式": self.paper_info.match_method,
            "期刊主页": self.paper_info.journal_profile_url,
            "影响因子": self.paper_info.impact_factor,
            "影响因子年份": self.paper_info.impact_factor_year,
            "影响因子来源": self.paper_info.impact_factor_source,
            "影响因子状态": self.paper_info.impact_factor_status,
            "年份": self.paper_info.year,
            "研究类型": self.paper_info.research_type,
            "发光材料类型": self.paper_info.emitter_type,
            "器件结构": "\n".join(structures) if structures else None,
            "EQE": "\n".join(eqes) if eqes else None,
            "CIE": "\n".join(cies) if cies else None,
            "寿命": "\n".join(lifetimes) if lifetimes else None,
            "最高EQE": self.paper_info.best_eqe,
            "优化层级": self.optimization.level if self.optimization else None,
            "优化策略": self.paper_info.optimization_strategy,
            "优化详情": self.optimization.strategy if self.optimization else None,
            "关键发现": self.optimization.key_findings if self.optimization else None,
            "EQE原文": self.data_source.eqe_source,
            "CIE原文": self.data_source.cie_source,
            "寿命原文": self.data_source.lifetime_source,
            "结构原文": self.data_source.structure_source,
        }
    
    def get_best_device(self) -> Optional[DeviceData]:
        """获取最佳性能器件（基于 EQE 数值）"""
        if not self.devices:
            return None
        
        best_device = None
        best_eqe_value = -1
        
        for device in self.devices:
            if device.eqe:
                # 尝试提取 EQE 数值
                match = re.search(r'(\d+\.?\d*)', device.eqe.replace('%', ''))
                if match:
                    eqe_value = float(match.group(1))
                    if eqe_value > best_eqe_value:
                        best_eqe_value = eqe_value
                        best_device = device
        
        return best_device or self.devices[0]


class ExtractionResult(BaseModel):
    """
    提取结果包装模型
    
    包含提取的数据和元信息（处理状态、来源文件等）。
    """
    
    model_config = ConfigDict(extra='forbid')
    
    success: bool = Field(
        default=True,
        description="提取是否成功"
    )
    
    data: Optional[PaperData] = Field(
        default=None,
        description="提取的论文数据"
    )
    
    source_file: Optional[str] = Field(
        default=None,
        description="源文件路径"
    )
    
    error_message: Optional[str] = Field(
        default=None,
        description="错误信息（如果失败）"
    )
    
    processing_time: Optional[float] = Field(
        default=None,
        description="处理耗时（秒）"
    )
    
    extraction_method: Optional[str] = Field(
        default=None,
        description="提取方法：'llm' 或 'regex'"
    )
    
    llm_model: Optional[str] = Field(
        default=None,
        description="使用的 LLM 模型（如果使用 LLM 提取）"
    )

    def __getitem__(self, key: str):
        """
        兼容旧版字典式访问。

        优先返回 to_excel_row() 中的扁平字段；若命中 data_source，则返回嵌套映射。
        """
        if not self.data:
            raise KeyError(key)

        flattened = self.data.to_excel_row()
        if key in flattened:
            return flattened[key]

        if key == "data_source":
            return self.data.data_source.model_dump()

        dumped = self.data.model_dump()
        if key in dumped:
            return dumped[key]

        raise KeyError(key)


# JSON Schema 用于 LLM Prompt
PAPER_DATA_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "paper_info": {
            "type": "object",
            "properties": {
                "title": {"type": ["string", "null"]},
                "authors": {"type": ["string", "null"]},
                "journal_name": {"type": ["string", "null"]},
                "raw_journal_title": {"type": ["string", "null"]},
                "raw_issn": {"type": ["string", "null"]},
                "raw_eissn": {"type": ["string", "null"]},
                "matched_journal_title": {"type": ["string", "null"]},
                "matched_issn": {"type": ["string", "null"]},
                "match_method": {"type": ["string", "null"]},
                "journal_profile_url": {"type": ["string", "null"]},
                "impact_factor": {"type": ["number", "null"]},
                "impact_factor_year": {"type": ["integer", "null"]},
                "impact_factor_source": {"type": ["string", "null"]},
                "impact_factor_status": {"type": ["string", "null"]},
                "year": {"type": ["integer", "null"]},
                "optimization_strategy": {"type": ["string", "null"]},
                "best_eqe": {"type": ["string", "null"]},
                "research_type": {"type": ["string", "null"]},
                "emitter_type": {"type": ["string", "null"]}
            },
            "required": []
        },
        "devices": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "device_label": {"type": ["string", "null"]},
                    "structure": {"type": ["string", "null"]},
                    "eqe": {"type": ["string", "null"]},
                    "cie": {"type": ["string", "null"]},
                    "lifetime": {"type": ["string", "null"]},
                    "luminance": {"type": ["string", "null"]},
                    "current_efficiency": {"type": ["string", "null"]},
                    "power_efficiency": {"type": ["string", "null"]},
                    "notes": {"type": ["string", "null"]}
                },
                "required": []
            }
        },
        "data_source": {
            "type": "object",
            "properties": {
                "eqe_source": {"type": ["string", "null"]},
                "cie_source": {"type": ["string", "null"]},
                "lifetime_source": {"type": ["string", "null"]},
                "structure_source": {"type": ["string", "null"]}
            },
            "required": []
        },
        "optimization": {
            "type": ["object", "null"],
            "properties": {
                "level": {"type": ["string", "null"]},
                "strategy": {"type": ["string", "null"]},
                "key_findings": {"type": ["string", "null"]}
            },
            "required": []
        }
    },
    "required": ["paper_info", "devices", "data_source"]
}
