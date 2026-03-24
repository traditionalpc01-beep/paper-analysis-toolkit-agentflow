"""
期刊影响因子数据库

包含主流期刊的名称、别名和合理的IF值范围（2024年数据）
用于验证IF查询结果的合理性

自动年份检测：
- 启动时会自动检测当前年份与数据库年份是否一致
- 如果不一致会输出警告日志
- 版本信息保存在 ~/.paperinsight/if_database_version.json
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import re


@dataclass(frozen=True)
class JournalIFRecord:
    name: str
    if_value: float
    if_year: int
    issn: Optional[str] = None
    eissn: Optional[str] = None


JOURNAL_IF_DATABASE: dict[str, JournalIFRecord] = {
    "nature": JournalIFRecord("Nature", 50.5, 2024, "0028-0836", "1476-4687"),
    "science": JournalIFRecord("Science", 44.7, 2024, "0036-8075", "1095-9203"),
    "cell": JournalIFRecord("Cell", 45.5, 2024, "0092-8674", "1097-4172"),
    "lancet": JournalIFRecord("The Lancet", 168.9, 2024, "0140-6736", "1474-547X"),
    "nature medicine": JournalIFRecord("Nature Medicine", 58.7, 2024, "1078-8956", "1546-170X"),
    "nature photonics": JournalIFRecord("Nature Photonics", 49.7, 2024, "1749-4885", "1476-4227"),
    "nature nanotechnology": JournalIFRecord("Nature Nanotechnology", 37.2, 2024, "1748-3387", "1748-3395"),
    "nature materials": JournalIFRecord("Nature Materials", 37.2, 2024, "1476-1122", "1476-4660"),
    "nature energy": JournalIFRecord("Nature Energy", 49.7, 2024, "2056-9387", None),
    "nature communications": JournalIFRecord("Nature Communications", 14.7, 2024, "2041-1723", None),
    "nature electronics": JournalIFRecord("Nature Electronics", 33.2, 2024, "2575-4135", None),
    "nature chemistry": JournalIFRecord("Nature Chemistry", 21.4, 2024, "1755-4330", "1755-4349"),
    "nature catalysis": JournalIFRecord("Nature Catalysis", 37.8, 2024, "2520-1131", None),
    "nature reviews materials": JournalIFRecord("Nature Reviews Materials", 45.2, 2024, "2058-8437", None),
    "nature reviews chemistry": JournalIFRecord("Nature Reviews Chemistry", 36.6, 2024, "2397-3358", None),

    "science advances": JournalIFRecord("Science Advances", 11.7, 2024, "2375-2548", None),
    "science translational medicine": JournalIFRecord("Science Translational Medicine", 15.8, 2024, "1946-6234", "1946-6242"),
    "science robotics": JournalIFRecord("Science Robotics", 26.5, 2024, "2470-9476", None),
    "science immunology": JournalIFRecord("Science Immunology", 17.9, 2024, "2470-9468", None),

    "pnas": JournalIFRecord("PNAS", 11.1, 2024, "0027-8424", "1091-6490"),
    "pnas nexus": JournalIFRecord("PNAS Nexus", 6.5, 2024, None, None),

    "chemical reviews": JournalIFRecord("Chemical Reviews", 52.8, 2024, "0009-2665", "1520-6890"),
    "chemical society reviews": JournalIFRecord("Chemical Society Reviews", 46.2, 2024, "0306-0012", "1460-4744"),
    "nature chemistry": JournalIFRecord("Nature Chemistry", 21.4, 2024, "1755-4330", "1755-4349"),

    "journal of the american chemical society": JournalIFRecord("Journal of the American Chemical Society", 15.6, 2024, "0002-7863", "1520-5126"),
    "jacs": JournalIFRecord("Journal of the American Chemical Society", 15.6, 2024, "0002-7863", "1520-5126"),

    "angewandte chemie": JournalIFRecord("Angewandte Chemie", 16.1, 2024, "0044-8249", "1521-3773"),
    "angewandte chemie international edition": JournalIFRecord("Angewandte Chemie International Edition", 16.1, 2024, "1433-7851", "1521-3773"),

    "energy & environmental science": JournalIFRecord("Energy & Environmental Science", 32.4, 2024, "1754-5692", "1754-5706"),
    "ees": JournalIFRecord("Energy & Environmental Science", 32.4, 2024, "1754-5692", "1754-5706"),

    "advanced materials": JournalIFRecord("Advanced Materials", 26.8, 2024, "0935-9648", "1521-4095"),
    "adv. mater.": JournalIFRecord("Advanced Materials", 26.8, 2024, "0935-9648", "1521-4095"),
    "advanced functional materials": JournalIFRecord("Advanced Functional Materials", 18.5, 2024, "1616-301X", "1616-3028"),
    "adv. funct. mater.": JournalIFRecord("Advanced Functional Materials", 18.5, 2024, "1616-301X", "1616-3028"),
    "advanced optical materials": JournalIFRecord("Advanced Optical Materials", 14.5, 2024, "2195-1071", None),
    "adv. opt. mater.": JournalIFRecord("Advanced Optical Materials", 14.5, 2024, "2195-1071", None),
    "advanced energy materials": JournalIFRecord("Advanced Energy Materials", 24.7, 2024, "1614-6832", "1614-6840"),
    "adv. energy mater.": JournalIFRecord("Advanced Energy Materials", 24.7, 2024, "1614-6832", "1614-6840"),
    "advanced science": JournalIFRecord("Advanced Science", 15.1, 2024, "2198-3844", None),
    "adv. sci.": JournalIFRecord("Advanced Science", 15.1, 2024, "2198-3844", None),
    "advanced healthcare materials": JournalIFRecord("Advanced Healthcare Materials", 10.0, 2024, "2046-2069", "2046-2077"),

    "small": JournalIFRecord("Small", 13.0, 2024, "1613-6810", "1613-6829"),
    "small methods": JournalIFRecord("Small Methods", 12.4, 2024, "2366-9608", None),
    "small structures": JournalIFRecord("Small Structures", 11.5, 2024, None, None),

    "nano letters": JournalIFRecord("Nano Letters", 10.8, 2024, "1530-6984", "1530-6992"),
    "nano lett.": JournalIFRecord("Nano Letters", 10.8, 2024, "1530-6984", "1530-6992"),
    "acs nano": JournalIFRecord("ACS Nano", 16.0, 2024, "1936-0851", "1936-086X"),
    "nature nanotechnology": JournalIFRecord("Nature Nanotechnology", 37.2, 2024, "1748-3387", "1748-3395"),

    "nano today": JournalIFRecord("Nano Today", 13.2, 2024, "1748-0132", "1878-0444"),
    "nano energy": JournalIFRecord("Nano Energy", 16.0, 2024, "2211-2855", "2211-3266"),
    "nano research": JournalIFRecord("Nano Research", 9.9, 2024, "1998-0124", "1998-0000"),
    "nano res.": JournalIFRecord("Nano Research", 9.9, 2024, "1998-0124", "1998-0000"),
    "nanoscale": JournalIFRecord("Nanoscale", 5.8, 2024, "2040-3364", "2040-3372"),
    "nanoscale horizons": JournalIFRecord("Nanoscale Horizons", 9.3, 2024, "2055-6756", None),
    "acs applied materials & interfaces": JournalIFRecord("ACS Applied Materials & Interfaces", 8.5, 2024, "1944-8244", "1944-8252"),
    "acs materials letters": JournalIFRecord("ACS Materials Letters", 11.2, 2024, None, None),
    "chemistry of materials": JournalIFRecord("Chemistry of Materials", 8.6, 2024, "0897-4756", "1520-5002"),
    "chem. mater.": JournalIFRecord("Chemistry of Materials", 8.6, 2024, "0897-4756", "1520-5002"),
    "acs catalysis": JournalIFRecord("ACS Catalysis", 12.8, 2024, "2155-5435", "2155-5435"),
    "acs energy letters": JournalIFRecord("ACS Energy Letters", 13.0, 2024, "2380-8195", "2380-8195"),
    "acs photonics": JournalIFRecord("ACS Photonics", 6.8, 2024, "2379-5198", "2379-5198"),
    "acs sensors": JournalIFRecord("ACS Sensors", 8.2, 2024, "2379-9160", "2379-9160"),
    "acs chemical biology": JournalIFRecord("ACS Chemical Biology", 5.5, 2024, "1554-8929", "1554-8937"),
    "bioconjugate chemistry": JournalIFRecord("Bioconjugate Chemistry", 5.1, 2024, "1043-1802", "1520-4812"),
    "chemistry - a european journal": JournalIFRecord("Chemistry - A European Journal", 4.1, 2024, "0947-6539", "1521-3765"),
    "chinese journal of catalysis": JournalIFRecord("Chinese Journal of Catalysis", 6.5, 2024, "0253-9837", "2210-3143"),

    "journal of materials chemistry a": JournalIFRecord("Journal of Materials Chemistry A", 10.7, 2024, "2050-7488", "2050-7496"),
    "j. mater. chem. a": JournalIFRecord("Journal of Materials Chemistry A", 10.7, 2024, "2050-7488", "2050-7496"),
    "journal of materials chemistry b": JournalIFRecord("Journal of Materials Chemistry B", 7.9, 2024, "2050-750X", "2050-7518"),
    "j. mater. chem. b": JournalIFRecord("Journal of Materials Chemistry B", 7.9, 2024, "2050-750X", "2050-7518"),
    "journal of materials chemistry c": JournalIFRecord("Journal of Materials Chemistry C", 5.5, 2024, "2050-7526", "2050-7534"),
    "j. mater. chem. c": JournalIFRecord("Journal of Materials Chemistry C", 5.5, 2024, "2050-7526", "2050-7534"),

    "physical review letters": JournalIFRecord("Physical Review Letters", 8.1, 2024, "0031-9007", "1079-7114"),
    "phys. rev. lett.": JournalIFRecord("Physical Review Letters", 8.1, 2024, "0031-9007", "1079-7114"),
    "prl": JournalIFRecord("Physical Review Letters", 8.1, 2024, "0031-9007", "1079-7114"),
    "physical review x": JournalIFRecord("Physical Review X", 11.6, 2024, "2160-3308", None),
    "reviews of modern physics": JournalIFRecord("Reviews of Modern Physics", 36.5, 2024, "0034-6861", "1539-0756"),
    "rev. mod. phys.": JournalIFRecord("Reviews of Modern Physics", 36.5, 2024, "0034-6861", "1539-0756"),
    "physical review applied": JournalIFRecord("Physical Review Applied", 5.8, 2024, "2331-7019", None),
    "physical review b": JournalIFRecord("Physical Review B", 3.6, 2024, "2469-9950", "2469-9969"),
    "phys. rev. b": JournalIFRecord("Physical Review B", 3.6, 2024, "2469-9950", "2469-9969"),
    "physical review materials": JournalIFRecord("Physical Review Materials", 4.2, 2024, "2475-9953", None),
    "physical review photonics": JournalIFRecord("Physical Review Photonics", 3.2, 2024, None, None),

    "light: science & applications": JournalIFRecord("Light: Science & Applications", 20.6, 2024, "2095-5545", "2047-7538"),
    "laser & photonics reviews": JournalIFRecord("Laser & Photonics Reviews", 9.8, 2024, "1863-8880", "1863-8899"),
    "laser photonics reviews": JournalIFRecord("Laser & Photonics Reviews", 9.8, 2024, "1863-8880", "1863-8899"),
    "advanced photonics": JournalIFRecord("Advanced Photonics", 17.3, 2024, None, None),
    "optica": JournalIFRecord("Optica", 10.4, 2024, "2334-2536", None),
    "optics express": JournalIFRecord("Optics Express", 3.8, 2024, "1094-4087", None),
    "optics letters": JournalIFRecord("Optics Letters", 3.6, 2024, "0146-9592", "1539-4794"),
    "photonics research": JournalIFRecord("Photonics Research", 7.6, 2024, "2327-9125", "2327-9125"),
    "nanophotonics": JournalIFRecord("Nanophotonics", 7.3, 2024, "1862-9118", "1862-9118"),

    "applied physics letters": JournalIFRecord("Applied Physics Letters", 3.5, 2024, "0003-6951", "1077-3118"),
    "appl. phys. lett.": JournalIFRecord("Applied Physics Letters", 3.5, 2024, "0003-6951", "1077-3118"),
    "journal of applied physics": JournalIFRecord("Journal of Applied Physics", 3.3, 2024, "0021-8979", "1089-7550"),
    "j. appl. phys.": JournalIFRecord("Journal of Applied Physics", 3.3, 2024, "0021-8979", "1089-7550"),
    "applied physics reviews": JournalIFRecord("Applied Physics Reviews", 10.7, 2024, "1931-9401", None),
    "apl materials": JournalIFRecord("APL Materials", 6.4, 2024, "2166-532X", None),
    "apl photonics": JournalIFRecord("APL Photonics", 5.6, 2024, None, None),
    "apl electronics materials": JournalIFRecord("APL Electronic Materials", 5.2, 2024, None, None),

    "scientific reports": JournalIFRecord("Scientific Reports", 3.8, 2024, "2045-2322", None),
    "nature scientific reports": JournalIFRecord("Scientific Reports", 3.8, 2024, "2045-2322", None),
    "plos one": JournalIFRecord("PLOS ONE", 3.7, 2024, "1932-6203", None),
    "pnas": JournalIFRecord("PNAS", 11.1, 2024, "0027-8424", "1091-6490"),
    "cell reports": JournalIFRecord("Cell Reports", 7.5, 2024, "2211-1247", None),
    "cell reports medicine": JournalIFRecord("Cell Reports Medicine", 13.1, 2024, "2666-3791", None),
    "cell reports physical science": JournalIFRecord("Cell Reports Physical Science", 8.5, 2024, None, None),
    "molecular cell": JournalIFRecord("Molecular Cell", 14.5, 2024, "1097-2765", "1097-4164"),
    "developmental cell": JournalIFRecord("Developmental Cell", 10.7, 2024, "1534-5807", "1878-1551"),
    "cell stem cell": JournalIFRecord("Cell Stem Cell", 19.8, 2024, "1934-5909", "1875-9777"),
    "cell metabolism": JournalIFRecord("Cell Metabolism", 27.4, 2024, "1550-4131", "1932-7420"),
    "cancer cell": JournalIFRecord("Cancer Cell", 50.3, 2024, "1535-6108", "1878-3686"),
    "neuron": JournalIFRecord("Neuron", 14.5, 2024, "0896-6273", "1097-4199"),
    "immunity": JournalIFRecord("Immunity", 25.9, 2024, "1074-7613", "1097-4180"),
    "molecular cell": JournalIFRecord("Molecular Cell", 14.5, 2024, "1097-2765", "1097-4164"),

    "nature biotechnology": JournalIFRecord("Nature Biotechnology", 32.1, 2024, "1087-0156", "1546-1696"),
    "nature methods": JournalIFRecord("Nature Methods", 36.1, 2024, "1548-7091", "1548-7105"),
    "nature genetics": JournalIFRecord("Nature Genetics", 31.7, 2024, "1061-4036", "1546-1718"),
    "nature immunology": JournalIFRecord("Nature Immunology", 22.8, 2024, "1529-2908", "1529-2916"),
    "nature cell biology": JournalIFRecord("Nature Cell Biology", 21.3, 2024, "1465-7392", "1476-4679"),
    "nature neuroscience": JournalIFRecord("Nature Neuroscience", 19.4, 2024, "1097-6256", "1546-1726"),
    "nature psychiatry": JournalIFRecord("Nature Mental Health", 11.2, 2024, None, None),
    "nature human behaviour": JournalIFRecord("Nature Human Behaviour", 21.4, 2024, "2397-334X", None),
    "nature communications": JournalIFRecord("Nature Communications", 14.7, 2024, "2041-1723", None),

    "chem": JournalIFRecord("Chem", 19.3, 2024, "2451-9308", None),
    "joule": JournalIFRecord("Joule", 27.8, 2024, "2542-4351", None),
    "matter": JournalIFRecord("Matter", 17.3, 2024, "2590-2385", None),
    "cell metabolism": JournalIFRecord("Cell Metabolism", 27.4, 2024, "1550-4131", "1932-7420"),
    "trends in chemistry": JournalIFRecord("Trends in Chemistry", 14.4, 2024, "2585-9067", None),
    "trends in catalysis": JournalIFRecord("Trends in Catalysis", 12.3, 2024, "2589-5970", None),

    "nature protocols": JournalIFRecord("Nature Protocols", 10.7, 2024, "1754-2184", "1754-2184"),
    "nature methods": JournalIFRecord("Nature Methods", 36.1, 2024, "1548-7091", "1548-7105"),
    "nature microbiology": JournalIFRecord("Nature Microbiology", 20.5, 2024, "2058-5276", None),
    "nature immunology": JournalIFRecord("Nature Immunology", 22.8, 2024, "1529-2908", "1529-2916"),

    "chemical engineering journal": JournalIFRecord("Chemical Engineering Journal", 13.3, 2024, "1385-8947", "1876-1070"),
    "chem. eng. j.": JournalIFRecord("Chemical Engineering Journal", 13.3, 2024, "1385-8947", "1876-1070"),
    "cej": JournalIFRecord("Chemical Engineering Journal", 13.3, 2024, "1385-8947", "1876-1070"),
    "separation and purification technology": JournalIFRecord("Separation and Purification Technology", 8.1, 2024, "1383-5866", "1873-3794"),
    "journal of membrane science": JournalIFRecord("Journal of Membrane Science", 8.4, 2024, "0376-7388", "1873-3113"),
    "desalination": JournalIFRecord("Desalination", 8.2, 2024, "0011-9164", "1873-4464"),
    "water research": JournalIFRecord("Water Research", 11.4, 2024, "0043-1354", "1879-2448"),

    "journal of power sources": JournalIFRecord("Journal of Power Sources", 8.1, 2024, "0378-7753", "1873-2755"),
    "j. power sources": JournalIFRecord("Journal of Power Sources", 8.1, 2024, "0378-7753", "1873-2755"),
    "energy storage materials": JournalIFRecord("Energy Storage Materials", 18.5, 2024, "2405-8297", "2405-8300"),
    "energy storage materials smart and sustainable": JournalIFRecord("Energy Storage Materials Smart and Sustainable", 9.8, 2024, None, None),
    "battery energy": JournalIFRecord("Battery Energy", 5.2, 2024, None, None),
    "battery communications": JournalIFRecord("Battery Communications", 4.5, 2024, None, None),

    "nature biomedical engineering": JournalIFRecord("Nature Biomedical Engineering", 27.4, 2024, "2157-846X", None),
    "biomaterials": JournalIFRecord("Biomaterials", 14.0, 2024, "0142-9612", "1878-5905"),
    "biosensors and bioelectronics": JournalIFRecord("Biosensors and Bioelectronics", 10.7, 2024, "0956-5663", "1873-4235"),
    "acta biomaterialia": JournalIFRecord("Acta Biomaterialia", 9.4, 2024, "1742-7061", "1878-7568"),
    "advanced healthcare materials": JournalIFRecord("Advanced Healthcare Materials", 10.0, 2024, "2046-2069", "2046-2077"),

    "nature electronics": JournalIFRecord("Nature Electronics", 33.2, 2024, "2575-4135", None),
    "nature biomedical engineering": JournalIFRecord("Nature Biomedical Engineering", 27.4, 2024, "2157-846X", None),
    "nature energy": JournalIFRecord("Nature Energy", 49.7, 2024, "2056-9387", None),

    "nature sustainability": JournalIFRecord("Nature Sustainability", 20.4, 2024, "2398-9629", None),
    "nature climate change": JournalIFRecord("Nature Climate Change", 19.6, 2024, "1758-678X", "1758-6798"),
    "nature food": JournalIFRecord("Nature Food", 16.9, 2024, "2662-1355", None),

    "nature communications": JournalIFRecord("Nature Communications", 14.7, 2024, "2041-1723", None),
    "science advances": JournalIFRecord("Science Advances", 11.7, 2024, "2375-2548", None),
    "pnas": JournalIFRecord("PNAS", 11.1, 2024, "0027-8424", "1091-6490"),
    "plos biology": JournalIFRecord("PLOS Biology", 7.8, 2024, "1544-9173", "1545-7885"),

    "nature physics": JournalIFRecord("Nature Physics", 17.6, 2024, "1745-2473", "1745-2481"),
    "nature materials": JournalIFRecord("Nature Materials", 37.2, 2024, "1476-1122", "1476-4660"),
    "nature nanotechnology": JournalIFRecord("Nature Nanotechnology", 37.2, 2024, "1748-3387", "1748-3395"),
    "nature photonics": JournalIFRecord("Nature Photonics", 49.7, 2024, "1749-4885", "1476-4227"),

    "nature reviews physics": JournalIFRecord("Nature Reviews Physics", 43.2, 2024, "2522-5820", None),
    "nature reviews materials": JournalIFRecord("Nature Reviews Materials", 45.2, 2024, "2058-8437", None),
    "nature reviews chemistry": JournalIFRecord("Nature Reviews Chemistry", 36.6, 2024, "2397-3358", None),
    "nature reviews genetics": JournalIFRecord("Nature Reviews Genetics", 42.7, 2024, "1471-0056", "1471-0064"),
    "nature reviews immunology": JournalIFRecord("Nature Reviews Immunology", 53.9, 2024, "1474-1733", "1474-1741"),
    "nature reviews neuroscience": JournalIFRecord("Nature Reviews Neuroscience", 28.6, 2024, "1471-003X", "1471-0048"),

    "trends in cell biology": JournalIFRecord("Trends in Cell Biology", 13.0, 2024, "0962-8924", "1879-0308"),
    "trends in biochemical sciences": JournalIFRecord("Trends in Biochemical Sciences", 11.5, 2024, "0968-0004", "1367-5931"),
    "trends in molecular medicine": JournalIFRecord("Trends in Molecular Medicine", 8.6, 2024, "1471-499X", "1471-499X"),
    "trends in pharmacological sciences": JournalIFRecord("Trends in Pharmacological Sciences", 7.8, 2024, "0165-6147", "1873-3735"),
    "trends in biotechnology": JournalIFRecord("Trends in Biotechnology", 11.6, 2024, "0167-7799", "1879-0961"),
    "trends in ecology & evolution": JournalIFRecord("Trends in Ecology & Evolution", 11.3, 2024, "0169-5347", "1872-8383"),
    "trends in neurosciences": JournalIFRecord("Trends in Neurosciences", 11.4, 2024, "0166-2236", "1878-008X"),
    "trends in catalysis": JournalIFRecord("Trends in Catalysis", 12.3, 2024, "2589-5970", None),
    "trends in chemistry": JournalIFRecord("Trends in Chemistry", 14.4, 2024, "2585-9067", None),

    "journal of clinical investigation": JournalIFRecord("Journal of Clinical Investigation", 15.4, 2024, "0021-9738", "1558-8238"),
    "jci": JournalIFRecord("Journal of Clinical Investigation", 15.4, 2024, "0021-9738", "1558-8238"),
    "journal of clinical oncology": JournalIFRecord("Journal of Clinical Oncology", 42.1, 2024, "0732-183X", "1527-7755"),
    "jco": JournalIFRecord("Journal of Clinical Oncology", 42.1, 2024, "0732-183X", "1527-7755"),
    "blood": JournalIFRecord("Blood", 17.3, 2024, "0006-4971", "1528-0020"),
    "circulation": JournalIFRecord("Circulation", 35.5, 2024, "0009-7322", "1524-4539"),
    "circulation research": JournalIFRecord("Circulation Research", 16.9, 2024, "0009-7330", "1434-1880"),
    "journal of the american college of cardiology": JournalIFRecord("Journal of the American College of Cardiology", 13.5, 2024, "0735-1097", "1558-3597"),
    "jacc": JournalIFRecord("Journal of the American College of Cardiology", 13.5, 2024, "0735-1097", "1558-3597"),
    "nature medicine": JournalIFRecord("Nature Medicine", 58.7, 2024, "1078-8956", "1546-170X"),
    "lancet oncology": JournalIFRecord("The Lancet Oncology", 35.9, 2024, "1470-2045", "1474-5488"),
    "lancet neurology": JournalIFRecord("The Lancet Neurology", 28.1, 2024, "1474-4422", "1474-4422"),
    "lancet infectious diseases": JournalIFRecord("The Lancet Infectious Diseases", 21.4, 2024, "1473-3099", "1474-4457"),
    "lancet diabetes & endocrinology": JournalIFRecord("The Lancet Diabetes & Endocrinology", 29.3, 2024, "2213-8587", "2213-8595"),

    "advanced materials": JournalIFRecord("Advanced Materials", 26.8, 2024, "0935-9648", "1521-4095"),
    "adv. mater.": JournalIFRecord("Advanced Materials", 26.8, 2024, "0935-9648", "1521-4095"),
    "advanced functional materials": JournalIFRecord("Advanced Functional Materials", 18.5, 2024, "1616-301X", "1616-3028"),
    "adv. funct. mater.": JournalIFRecord("Advanced Functional Materials", 18.5, 2024, "1616-301X", "1616-3028"),

    "account of chemical research": JournalIFRecord("Accounts of Chemical Research", 15.4, 2024, "0001-4842", "1520-4898"),
    "account chem res": JournalIFRecord("Accounts of Chemical Research", 15.4, 2024, "0001-4842", "1520-4898"),

    "nature catalysis": JournalIFRecord("Nature Catalysis", 37.8, 2024, "2520-1131", None),
    "acs catalysis": JournalIFRecord("ACS Catalysis", 12.8, 2024, "2155-5435", "2155-5435"),
    "catalysis science & technology": JournalIFRecord("Catalysis Science & Technology", 5.2, 2024, "2044-4753", "2044-4761"),
    "green chemistry": JournalIFRecord("Green Chemistry", 8.4, 2024, "1463-9262", "1463-9272"),
    "green energy & environment": JournalIFRecord("Green Energy & Environment", 9.5, 2024, None, None),

    "nature computational science": JournalIFRecord("Nature Computational Science", 10.8, 2024, "2662-8457", None),
    "nature machine intelligence": JournalIFRecord("Nature Machine Intelligence", 18.5, 2024, "2522-5839", None),
    "nature human behaviour": JournalIFRecord("Nature Human Behaviour", 21.4, 2024, "2397-334X", None),
    "nature methods": JournalIFRecord("Nature Methods", 36.1, 2024, "1548-7091", "1548-7105"),
    "nature protocols": JournalIFRecord("Nature Protocols", 10.7, 2024, "1754-2184", "1754-2184"),

    "npj computational materials": JournalIFRecord("npj Computational Materials", 10.2, 2024, "2057-3960", None),
    "npj quantum information": JournalIFRecord("npj Quantum Information", 8.1, 2024, "2056-6387", None),
    "npj 2d materials and applications": JournalIFRecord("npj 2D Materials and Applications", 11.2, 2024, "2397-4648", None),
    "npj flexible electronics": JournalIFRecord("npj Flexible Electronics", 10.5, 2024, None, None),
    "npj green sustainability": JournalIFRecord("npj Green Sustainability", 8.8, 2024, None, None),
    "npj clean water": JournalIFRecord("npj Clean Water", 12.2, 2024, None, None),
    "npj climate action": JournalIFRecord("npj Climate Action", 7.5, 2024, None, None),
    "npj nature sustainability": JournalIFRecord("Nature Sustainability", 20.4, 2024, "2398-9629", None),

    "science bulletin": JournalIFRecord("Science Bulletin", 18.9, 2024, "2095-9273", "2095-9281"),
    "science china chemistry": JournalIFRecord("Science China Chemistry", 6.8, 2024, "1674-7291", "1867-3880"),
    "science china materials": JournalIFRecord("Science China Materials", 6.1, 2024, "2095-8226", "2199-4501"),
    "science china physics mechanics & astronomy": JournalIFRecord("Science China Physics, Mechanics & Astronomy", 5.2, 2024, "1674-7348", "1869-1927"),
    "science china technological sciences": JournalIFRecord("Science China Technological Sciences", 4.8, 2024, "1674-7321", "1869-1900"),

    "national science review": JournalIFRecord("National Science Review", 11.0, 2024, "2095-5138", "2053-714X"),
    "nsr": JournalIFRecord("National Science Review", 11.0, 2024, "2095-5138", "2053-714X"),
    "quantum front": JournalIFRecord("Quantum Front", 4.5, 2024, None, None),
    "csb": JournalIFRecord("Chinese Science Bulletin", 18.9, 2024, "0023-074X", None),
    "chinese journal of catalysis": JournalIFRecord("Chinese Journal of Catalysis", 6.5, 2024, "0253-9837", "2210-3143"),
    "acta chimica sinica": JournalIFRecord("Acta Chimica Sinica", 6.2, 2024, "0567-7351", "1876-6048"),
    "journal of materials science & technology": JournalIFRecord("Journal of Materials Science & Technology", 10.9, 2024, "1005-0302", "2210-7628"),
    "jmst": JournalIFRecord("Journal of Materials Science & Technology", 10.9, 2024, "1005-0302", "2210-7628"),
    "rare metal materials and engineering": JournalIFRecord("Rare Metal Materials and Engineering", 1.8, 2024, "1002-185X", "1875-5372"),
    "journal of energy chemistry": JournalIFRecord("Journal of Energy Chemistry", 9.2, 2024, "2095-4956", "2210-7628"),
    "journal of rare earths": JournalIFRecord("Journal of Rare Earths", 5.8, 2024, "1001-0521", "1867-7188"),
    "frontiers in chemistry": JournalIFRecord("Frontiers in Chemistry", 4.1, 2024, "2296-2646", None),
    "frontiers in materials": JournalIFRecord("Frontiers in Materials", 3.5, 2024, "2297-1956", None),
    "frontiers in physics": JournalIFRecord("Frontiers in Physics", 3.2, 2024, "2296-424X", None),

    "nano-micro letters": JournalIFRecord("Nano-Micro Letters", 14.6, 2024, "2311-6706", "2150-5551"),
    "nano micro": JournalIFRecord("Nano-Micro Letters", 14.6, 2024, "2311-6706", "2150-5551"),
    "frontiers of physics": JournalIFRecord("Frontiers of Physics", 4.5, 2024, "2095-0462", "2095-0470"),
    "front. phys.": JournalIFRecord("Frontiers of Physics", 4.5, 2024, "2095-0462", "2095-0470"),
    "journal of materials chemistry a": JournalIFRecord("Journal of Materials Chemistry A", 10.7, 2024, "2050-7488", "2050-7496"),
    "journal of materials chemistry c": JournalIFRecord("Journal of Materials Chemistry C", 5.5, 2024, "2050-7526", "2050-7534"),
    "journal of materials chemistry": JournalIFRecord("Journal of Materials Chemistry", 8.0, 2024, "0959-9428", "1460-4744"),

    "light: science & applications": JournalIFRecord("Light: Science & Applications", 20.6, 2024, "2095-5545", "2047-7538"),
    "optics express": JournalIFRecord("Optics Express", 3.8, 2024, "1094-4087", None),
    "optics letters": JournalIFRecord("Optics Letters", 3.6, 2024, "0146-9592", "1539-4794"),
    "photonics research": JournalIFRecord("Photonics Research", 7.6, 2024, "2327-9125", "2327-9125"),
    "photoniX": JournalIFRecord("PhotoniX", 13.5, 2024, "2096-9119", None),

    "infomat": JournalIFRecord("InfoMat", 22.2, 2024, "2564-1588", "2564-1596"),
    "smartmat": JournalIFRecord("SmartMat", 13.5, 2024, "2688-040X", None),
    "nanoscale": JournalIFRecord("Nanoscale", 5.8, 2024, "2040-3364", "2040-3372"),
    "nanoscale advances": JournalIFRecord("Nanoscale Advances", 2.8, 2024, None, None),
    "journal of physics photonics research": JournalIFRecord("Journal of Physics: Photonics", 5.2, 2024, None, None),

    "electrochemical energy reviews": JournalIFRecord("Electrochemical Energy Reviews", 28.6, 2024, "2589-7736", None),
    "eetr": JournalIFRecord("Electrochemical Energy Reviews", 28.6, 2024, "2589-7736", None),
    "progress in materials science": JournalIFRecord("Progress in Materials Science", 31.5, 2024, "0079-6425", "1873-2204"),
    "prog. mater. sci.": JournalIFRecord("Progress in Materials Science", 31.5, 2024, "0079-6425", "1873-2204"),
    "progress in quantum electronics": JournalIFRecord("Progress in Quantum Electronics", 13.2, 2024, "0079-6425", "1873-2204"),
    "materials science & engineering r-reports": JournalIFRecord("Materials Science & Engineering R-Reports", 29.5, 2024, "0927-796X", "1875-0740"),
    "advances in colloid and interface science": JournalIFRecord("Advances in Colloid and Interface Science", 14.8, 2024, "0001-8686", "1873-2763"),
    "adv. colloid interface sci.": JournalIFRecord("Advances in Colloid and Interface Science", 14.8, 2024, "0001-8686", "1873-2763"),
    "surface science reports": JournalIFRecord("Surface Science Reports", 18.5, 2024, "0167-5729", "1879-2774"),
    "surf. sci. rep.": JournalIFRecord("Surface Science Reports", 18.5, 2024, "0167-5729", "1879-2774"),
    "reports on progress in physics": JournalIFRecord("Reports on Progress in Physics", 16.3, 2024, "0034-4885", "1361-6633"),
    "rep. prog. phys.": JournalIFRecord("Reports on Progress in Physics", 16.3, 2024, "0034-4885", "1361-6633"),

    "coordination chemistry reviews": JournalIFRecord("Coordination Chemistry Reviews", 14.8, 2024, "0010-8545", "1873-3480"),
    "coord. chem. rev.": JournalIFRecord("Coordination Chemistry Reviews", 14.8, 2024, "0010-8545", "1873-3480"),
    "inorganic chemistry": JournalIFRecord("Inorganic Chemistry", 4.6, 2024, "0020-1669", "1520-510X"),
    "inorg. chem.": JournalIFRecord("Inorganic Chemistry", 4.6, 2024, "0020-1669", "1520-510X"),
    "organic letters": JournalIFRecord("Organic Letters", 4.9, 2024, "1523-7060", "1523-7052"),
    "org. lett.": JournalIFRecord("Organic Letters", 4.9, 2024, "1523-7060", "1523-7052"),
    "organic chemistry frontiers": JournalIFRecord("Organic Chemistry Frontiers", 5.4, 2024, "2052-4129", "2052-4137"),
    "organic chemistry": JournalIFRecord("Organic Chemistry", 3.2, 2024, "2304-6740", None),

    "analytical chemistry": JournalIFRecord("Analytical Chemistry", 6.7, 2024, "0003-2700", "1520-6882"),
    "anal. chem.": JournalIFRecord("Analytical Chemistry", 6.7, 2024, "0003-2700", "1520-6882"),
    "environmental science & technology": JournalIFRecord("Environmental Science & Technology", 7.3, 2024, "0013-936X", "1520-5851"),
    "environ. sci. technol.": JournalIFRecord("Environmental Science & Technology", 7.3, 2024, "0013-936X", "1520-5851"),
    "environmental science & technology letters": JournalIFRecord("Environmental Science & Technology Letters", 5.8, 2024, "0000-0000", "2328-8930"),
    "jacs": JournalIFRecord("Journal of the American Chemical Society", 15.6, 2024, "0002-7863", "1520-5126"),

    "advances in physics": JournalIFRecord("Advances in Physics", 19.2, 2024, "0001-8732", "1460-6976"),
    "adv. phys.": JournalIFRecord("Advances in Physics", 19.2, 2024, "0001-8732", "1460-6976"),
    "annual review of condensed matter physics": JournalIFRecord("Annual Review of Condensed Matter Physics", 16.2, 2024, "1947-5454", "1947-5462"),
    "annu. rev. condens. matter phys.": JournalIFRecord("Annual Review of Condensed Matter Physics", 16.2, 2024, "1947-5454", "1947-5462"),

    "nature geoscience": JournalIFRecord("Nature Geoscience", 18.3, 2024, "1752-0894", "1752-0908"),
    "nature climate change": JournalIFRecord("Nature Climate Change", 19.6, 2024, "1758-678X", "1758-6798"),
    "earth and planetary science letters": JournalIFRecord("Earth and Planetary Science Letters", 4.8, 2024, "0012-821X", "1385-013X"),
    "geophysical research letters": JournalIFRecord("Geophysical Research Letters", 4.6, 2024, "0094-8276", "1944-8007"),
    "astrophysical journal": JournalIFRecord("The Astrophysical Journal", 4.7, 2024, "0004-637X", "2041-8213"),
    "astrophysical journal letters": JournalIFRecord("The Astrophysical Journal Letters", 5.1, 2024, "2041-8205", "2041-8213"),

    "cellular and molecular life sciences": JournalIFRecord("Cellular and Molecular Life Sciences", 6.8, 2024, "1420-682X", "1420-9071"),
    "cellular & molecular life sciences": JournalIFRecord("Cellular and Molecular Life Sciences", 6.8, 2024, "1420-682X", "1420-9071"),
    "journal of molecular cell biology": JournalIFRecord("Journal of Molecular Cell Biology", 5.5, 2024, "1674-2788", "1745-8270"),
    "cell discovery": JournalIFRecord("Cell Discovery", 10.4, 2024, "2056-5968", None),
    "cell reports": JournalIFRecord("Cell Reports", 7.5, 2024, "2211-1247", None),

    "nature microbiology": JournalIFRecord("Nature Microbiology", 20.5, 2024, "2058-5276", None),
    "nature immunology": JournalIFRecord("Nature Immunology", 22.8, 2024, "1529-2908", "1529-2916"),
    "nature neuroscience": JournalIFRecord("Nature Neuroscience", 19.4, 2024, "1097-6256", "1546-1726"),
    "nature psychiatry": JournalIFRecord("Nature Mental Health", 11.2, 2024, None, None),
    "trends in biochemical sciences": JournalIFRecord("Trends in Biochemical Sciences", 11.5, 2024, "0968-0004", "1367-5931"),

    "proceedings of the national academy of sciences": JournalIFRecord("Proceedings of the National Academy of Sciences", 11.1, 2024, "0027-8424", "1091-6490"),
    "proceedings of the national academy of sciences of the united states of america": JournalIFRecord("Proceedings of the National Academy of Sciences", 11.1, 2024, "0027-8424", "1091-6490"),
    "embo journal": JournalIFRecord("The EMBO Journal", 9.8, 2024, "0261-4189", "1460-2075"),
    "embo reports": JournalIFRecord("EMBO Reports", 5.5, 2024, "1469-221X", "1469-3178"),
    "molecular biology and evolution": JournalIFRecord("Molecular Biology and Evolution", 9.1, 2024, "0737-4038", "1537-1719"),
    "plos genetics": JournalIFRecord("PLOS Genetics", 4.5, 2024, "1553-7390", "1553-7404"),
    "plos biology": JournalIFRecord("PLOS Biology", 7.8, 2024, "1544-9173", "1545-7885"),
    "plos computational biology": JournalIFRecord("PLOS Computational Biology", 4.3, 2024, "1553-734X", "1553-7358"),
    "plos pathogens": JournalIFRecord("PLOS Pathogens", 5.7, 2024, "1553-7366", "1553-7374"),
    "plos one": JournalIFRecord("PLOS ONE", 3.7, 2024, "1932-6203", None),

    "nature communications": JournalIFRecord("Nature Communications", 14.7, 2024, "2041-1723", None),
    "science advances": JournalIFRecord("Science Advances", 11.7, 2024, "2375-2548", None),
    "pnas": JournalIFRecord("PNAS", 11.1, 2024, "0027-8424", "1091-6490"),
    "pnas nexus": JournalIFRecord("PNAS Nexus", 6.5, 2024, None, None),
    "scientific reports": JournalIFRecord("Scientific Reports", 3.8, 2024, "2045-2322", None),
    "nature scientific reports": JournalIFRecord("Scientific Reports", 3.8, 2024, "2045-2322", None),
    "iopscience": JournalIFRecord("IOP Publishing", 2.5, 2024, None, None),

    "frontiers in chemistry": JournalIFRecord("Frontiers in Chemistry", 4.1, 2024, "2296-2646", None),
    "frontiers in materials": JournalIFRecord("Frontiers in Materials", 3.5, 2024, "2297-1956", None),
    "frontiers in physics": JournalIFRecord("Frontiers in Physics", 3.2, 2024, "2296-424X", None),
    "frontiers in energy research": JournalIFRecord("Frontiers in Energy Research", 3.4, 2024, "2296-598X", None),

    "electrochimica acta": JournalIFRecord("Electrochimica Acta", 5.4, 2024, "0013-4686", "1873-3853"),
    "electrochima acta": JournalIFRecord("Electrochimica Acta", 5.4, 2024, "0013-4686", "1873-3853"),
    "journal of the electrochemical society": JournalIFRecord("Journal of the Electrochemical Society", 3.1, 2024, "0013-4651", "1945-7111"),
    "j. electrochem. soc.": JournalIFRecord("Journal of the Electrochemical Society", 3.1, 2024, "0013-4651", "1945-7111"),
    "energy & fuels": JournalIFRecord("Energy & Fuels", 5.2, 2024, "0887-0624", "1520-5029"),
    "energy fuels": JournalIFRecord("Energy & Fuels", 5.2, 2024, "0887-0624", "1520-5029"),
    "fuel": JournalIFRecord("Fuel", 7.2, 2024, "0016-2361", "1873-2155"),
    "fuel processing technology": JournalIFRecord("Fuel Processing Technology", 7.8, 2024, "0378-3820", "1873-718X"),
    "applied energy": JournalIFRecord("Applied Energy", 10.1, 2024, "0306-2619", "1872-9118"),
    "appl. energy": JournalIFRecord("Applied Energy", 10.1, 2024, "0306-2619", "1872-9118"),
    "energy conversion and management": JournalIFRecord("Energy Conversion and Management", 9.9, 2024, "0196-8904", "1879-2227"),
    "energy build.": JournalIFRecord("Energy and Buildings", 5.5, 2024, "0378-7788", "1872-5806"),
    "renewable energy": JournalIFRecord("Renewable Energy", 8.7, 2024, "0960-1481", "1879-0682"),
    "renewable and sustainable energy reviews": JournalIFRecord("Renewable and Sustainable Energy Reviews", 14.4, 2024, "1364-0321", "1879-0690"),
    "solar energy": JournalIFRecord("Solar Energy", 5.5, 2024, "0038-092X", "1479-5406"),
    "solar energy materials and solar cells": JournalIFRecord("Solar Energy Materials and Solar Cells", 6.3, 2024, "0927-0248", "1879-0988"),
    "solar energy materials": JournalIFRecord("Solar Energy Materials", 3.8, 2024, "0927-0248", None),

    "actuators": JournalIFRecord("Actuators", 2.1, 2024, "2076-0825", None),
    "sensors": JournalIFRecord("Sensors", 3.4, 2024, "1424-8220", None),
    "biosensors": JournalIFRecord("Biosensors", 5.1, 2024, "0956-5663", None),
    "talanta": JournalIFRecord("Talanta", 5.6, 2024, "0039-9140", "1873-3573"),
    "analytica chimica acta": JournalIFRecord("Analytica Chimica Acta", 5.4, 2024, "0003-2670", "1873-3565"),
    "anal. chim. acta": JournalIFRecord("Analytica Chimica Acta", 5.4, 2024, "0003-2670", "1873-3565"),
    "journal of chromatography a": JournalIFRecord("Journal of Chromatography A", 3.3, 2024, "0021-9673", "1873-3778"),
    "j. chromatogr. a": JournalIFRecord("Journal of Chromatography A", 3.3, 2024, "0021-9673", "1873-3778"),
    "food chemistry": JournalIFRecord("Food Chemistry", 7.7, 2024, "0308-8146", "1873-7072"),
    "food hydrocolloids": JournalIFRecord("Food Hydrocolloids", 5.3, 2024, "0268-005X", "1873-7137"),
    "carbohydrate polymers": JournalIFRecord("Carbohydrate Polymers", 9.4, 2024, "0144-8617", "1879-1340"),
    "carbohydrate polymer": JournalIFRecord("Carbohydrate Polymers", 9.4, 2024, "0144-8617", "1879-1340"),
    "international journal of biological macromolecules": JournalIFRecord("International Journal of Biological Macromolecules", 7.2, 2024, "0141-8130", "1879-0003"),
    "int. j. biol. macromol.": JournalIFRecord("International Journal of Biological Macromolecules", 7.2, 2024, "0141-8130", "1879-0003"),
    "polymer reviews": JournalIFRecord("Polymer Reviews", 12.8, 2024, "1558-3724", "1558-3716"),
    "polymer chemistry": JournalIFRecord("Polymer Chemistry", 4.5, 2024, "1759-9954", "1759-9962"),
    "polymer": JournalIFRecord("Polymer", 3.8, 2024, "0032-3861", None),
    "macromolecules": JournalIFRecord("Macromolecules", 5.1, 2024, "0024-9297", "1520-5835"),
    "acs macro letters": JournalIFRecord("ACS Macro Letters", 5.8, 2024, "2161-1653", "2161-1653"),
    "biomacromolecules": JournalIFRecord("Biomacromolecules", 5.3, 2024, "1525-7797", "1520-5827"),
    "soft matter": JournalIFRecord("Soft Matter", 3.2, 2024, "1744-683X", "1744-6848"),
    "langmuir": JournalIFRecord("Langmuir", 3.7, 2024, "0743-7463", "1520-5827"),
    "journal of colloid and interface science": JournalIFRecord("Journal of Colloid and Interface Science", 8.3, 2024, "0021-9797", "1095-7103"),
    "j. colloid interface sci.": JournalIFRecord("Journal of Colloid and Interface Science", 8.3, 2024, "0021-9797", "1095-7103"),
    "nanoscale": JournalIFRecord("Nanoscale", 5.8, 2024, "2040-3364", "2040-3372"),
    "nanoscale advances": JournalIFRecord("Nanoscale Advances", 2.8, 2024, None, None),

    "catalysis today": JournalIFRecord("Catalysis Today", 5.4, 2024, "0920-5861", "1873-4308"),
    "catal. today": JournalIFRecord("Catalysis Today", 5.4, 2024, "0920-5861", "1873-4308"),
    "applied catalysis b-environmental": JournalIFRecord("Applied Catalysis B: Environmental", 14.8, 2024, "0926-3373", "1873-3883"),
    "applied catalysis b": JournalIFRecord("Applied Catalysis B: Environmental", 14.8, 2024, "0926-3373", "1873-3883"),
    "applied catalysis a-general": JournalIFRecord("Applied Catalysis A: General", 4.2, 2024, "0926-860X", "1873-3889"),
    "journal of catalysis": JournalIFRecord("Journal of Catalysis", 6.8, 2024, "0021-9517", "1095-9269"),
    "j. catal.": JournalIFRecord("Journal of Catalysis", 6.8, 2024, "0021-9517", "1095-9269"),
    "chemical communications": JournalIFRecord("Chemical Communications", 4.9, 2024, "1359-7345", "1364-548X"),
    "chem. commun.": JournalIFRecord("Chemical Communications", 4.9, 2024, "1359-7345", "1364-548X"),
    "chemical science": JournalIFRecord("Chemical Science", 8.4, 2024, "2041-6529", "2041-6537"),
    "chem. sci.": JournalIFRecord("Chemical Science", 8.4, 2024, "2041-6529", "2041-6537"),
    "journal of materials chemistry a": JournalIFRecord("Journal of Materials Chemistry A", 10.7, 2024, "2050-7488", "2050-7496"),
    "journal of materials chemistry b": JournalIFRecord("Journal of Materials Chemistry B", 7.9, 2024, "2050-750X", "2050-7518"),
    "journal of materials chemistry c": JournalIFRecord("Journal of Materials Chemistry C", 5.5, 2024, "2050-7526", "2050-7534"),
    "crystal growth & design": JournalIFRecord("Crystal Growth & Design", 3.6, 2024, "1528-7483", "1528-7505"),
    "crystal growth & design": JournalIFRecord("Crystal Growth & Design", 3.6, 2024, "1528-7483", "1528-7505"),
    "journal of physical chemistry letters": JournalIFRecord("Journal of Physical Chemistry Letters", 5.7, 2024, "1948-7185", "1948-7185"),
    "j. phys. chem. lett.": JournalIFRecord("Journal of Physical Chemistry Letters", 5.7, 2024, "1948-7185", "1948-7185"),
    "journal of physical chemistry c": JournalIFRecord("Journal of Physical Chemistry C", 3.7, 2024, "1932-7447", "1932-7455"),
    "j. phys. chem. c": JournalIFRecord("Journal of Physical Chemistry C", 3.7, 2024, "1932-7447", "1932-7455"),
    "journal of physical chemistry a": JournalIFRecord("Journal of Physical Chemistry A", 2.8, 2024, "1089-5639", "1520-5215"),
    "j. phys. chem. a": JournalIFRecord("Journal of Physical Chemistry A", 2.8, 2024, "1089-5639", "1520-5215"),
    "physical chemistry chemical physics": JournalIFRecord("Physical Chemistry Chemical Physics", 3.3, 2024, "1463-9076", "1463-9084"),
    "phys. chem. chem. phys.": JournalIFRecord("Physical Chemistry Chemical Physics", 3.3, 2024, "1463-9076", "1463-9084"),
    "pccp": JournalIFRecord("Physical Chemistry Chemical Physics", 3.3, 2024, "1463-9076", "1463-9084"),
}


JOURNAL_ALIASES: dict[str, str] = {
    "adv funct materials": "advanced functional materials",
    "adv funct mater": "advanced functional materials",
    "adv. funct. mater.": "advanced functional materials",
    "adv. funct. materials": "advanced functional materials",
    "adv materials": "advanced materials",
    "adv. mater.": "advanced materials",
    "adv opt mater": "advanced optical materials",
    "adv. opt. mater.": "advanced optical materials",
    "adv energy mater": "advanced energy materials",
    "adv. energy mater.": "advanced energy materials",
    "adv sci": "advanced science",
    "adv. sci.": "advanced science",
    "adv healthc mater": "advanced healthcare materials",
    "adv. healthc mater.": "advanced healthcare materials",
    "nano lett": "nano letters",
    "nano lett.": "nano letters",
    "nano res": "nano research",
    "nano res.": "nano research",
    "jacs": "journal of the american chemical society",
    "j. am. chem. soc.": "journal of the american chemical society",
    "j am chem soc": "journal of the american chemical society",
    "angewandte": "angewandte chemie",
    "angew. chem.": "angewandte chemie",
    "ees": "energy & environmental science",
    "chem rev": "chemical reviews",
    "chem. rev.": "chemical reviews",
    "chem soc rev": "chemical society reviews",
    "chem. soc. rev.": "chemical society reviews",
    "prl": "physical review letters",
    "phys rev lett": "physical review letters",
    "phys. rev. lett.": "physical review letters",
    "rev mod phys": "reviews of modern physics",
    "rev. mod. phys.": "reviews of modern physics",
    "lpr": "laser & photonics reviews",
    "light": "light: science & applications",
    "sci bull": "science bulletin",
    "csb": "science bulletin",
    "nsr": "national science review",
    "jmst": "journal of materials science & technology",
    "pnas": "pnas",
    "nat commun": "nature communications",
    "nat photonics": "nature photonics",
    "nat nanotechnol": "nature nanotechnology",
    "nat mater": "nature materials",
    "nat energy": "nature energy",
    "nat catal": "nature catalysis",
    "nat chem": "nature chemistry",
    "nat med": "nature medicine",
    "nat biotech": "nature biotechnology",
    "nat methods": "nature methods",
    "nat genet": "nature genetics",
    "nat immunol": "nature immunology",
    "nat neurosci": "nature neuroscience",
    "nat electron": "nature electronics",
    "sci adv": "science advances",
    "sci transl med": "science translational medicine",
    "sci robot": "science robotics",
    "sci immunol": "science immunology",
    "cell rep": "cell reports",
    "mol cell": "molecular cell",
    "trends chem": "trends in chemistry",
    "trends catal": "trends in catalysis",
    "trends biochem sci": "trends in biochemical sciences",
    "trends cell biol": "trends in cell biology",
    "trends biotech": "trends in biotechnology",
    "trends neurosci": "trends in neurosciences",
    "trends ecol evol": "trends in ecology & evolution",
    "trends mol med": "trends in molecular medicine",
    "trends pharmacol sci": "trends in pharmacological sciences",
    "acc chem res": "account of chemical research",
    "acc. chem. res.": "account of chemical research",
    "coord chem rev": "coordination chemistry reviews",
    "coord. chem. rev.": "coordination chemistry reviews",
    "surf sci rep": "surface science reports",
    "surf. sci. rep.": "surface science reports",
    "prog mater sci": "progress in materials science",
    "prog. mater. sci.": "progress in materials science",
    "prog quantum electron": "progress in quantum electronics",
    "prog. quantum electron.": "progress in quantum electronics",
    "adv colloid interface sci": "advances in colloid and interface science",
    "adv. colloid interface sci.": "advances in colloid and interface science",
    "mater sci eng r": "materials science & engineering r-reports",
    "adv phys": "advances in physics",
    "adv. phys.": "advances in physics",
    "annu rev condens matter phys": "annual review of condensed matter physics",
    "annu. rev. cond. matter phys.": "annual review of condensed matter physics",
    "cej": "chemical engineering journal",
    "chem eng j": "chemical engineering journal",
    "chem. eng. j.": "chemical engineering journal",
    "j mem sci": "journal of membrane science",
    "j. mem. sci.": "journal of membrane science",
    "env sci technol": "environmental science & technology",
    "environ. sci. technol.": "environmental science & technology",
    "env sci technol lett": "environmental science & technology letters",
    "electrochim acta": "electrochimica acta",
    "electrochima acta": "electrochimica acta",
    "j electrochem soc": "journal of the electrochemical society",
    "j. electrochem. soc.": "journal of the electrochemical society",
    "int j biol macromol": "international journal of biological macromolecules",
    "int. j. biol. macromol.": "international journal of biological macromolecules",
    "carbohyd polym": "carbohydrate polymers",
    "carbohyd. polym.": "carbohydrate polymers",
    "anal chim acta": "analytica chimica acta",
    "anal. chim. acta": "analytica chimica acta",
    "j chromatogr a": "journal of chromatography a",
    "j. chromatogr. a": "journal of chromatography a",
    "crystal growth & design": "crystal growth & design",
    "phys chem chem phys": "physical chemistry chemical physics",
    "phys. chem. chem. phys.": "physical chemistry chemical physics",
    "j phys chem c": "journal of physical chemistry c",
    "j. phys. chem. c": "journal of physical chemistry c",
    "j phys chem lett": "journal of physical chemistry letters",
    "j. phys. chem. lett.": "journal of physical chemistry letters",
    "j phys chem a": "journal of physical chemistry a",
    "j. phys. chem. a": "journal of physical chemistry a",
    "appl catal b": "applied catalysis b-environmental",
    "appl. catal. b": "applied catalysis b-environmental",
    "appl catal a": "applied catalysis a-general",
    "appl. catal. a": "applied catalysis a-general",
    "j catal": "journal of catalysis",
    "j. catal.": "journal of catalysis",
    "chem commun": "chemical communications",
    "chem. commun.": "chemical communications",
    "chem sci": "chemical science",
    "chem. sci.": "chemical science",
    "j mater chem a": "journal of materials chemistry a",
    "j. mater. chem. a": "journal of materials chemistry a",
    "j mater chem b": "journal of materials chemistry b",
    "j. mater. chem. b": "journal of materials chemistry b",
    "j mater chem c": "journal of materials chemistry c",
    "j. mater. chem. c": "journal of materials chemistry c",
    "soft matter": "soft matter",
    "langmuir": "langmuir",
    "macromolecules": "macromolecules",
    "acs macro lett": "acs macro letters",
    "biomacromolecules": "biomacromolecules",
    "polym chem": "polymer chemistry",
    "polym. chem.": "polymer chemistry",
    "polym rev": "polymer reviews",
    "polym. rev.": "polymer reviews",
    "food chem": "food chemistry",
    "food hydrocoll": "food hydrocolloids",
    "talanta": "talanta",
    "sensors": "sensors",
    "biosensors": "biosensors",
    "actuators": "actuators",
    "solar energy": "solar energy",
    "solar energy mater sol cells": "solar energy materials and solar cells",
    "appl energy": "applied energy",
    "appl. energy": "applied energy",
    "energy convers manage": "energy conversion and management",
    "energy convers. manage.": "energy conversion and management",
    "energy fuels": "energy & fuels",
    "fuel": "fuel",
    "fuel process technol": "fuel processing technology",
    "fuel process. technol.": "fuel processing technology",
    "renew energy": "renewable energy",
    "renewable sustainable energy rev": "renewable and sustainable energy reviews",
    "renewable sustainable energy rev.": "renewable and sustainable energy reviews",
    "water res": "water research",
    "water res.": "water research",
    "desalination": "desalination",
    "sep purif technol": "separation and purification technology",
    "sep. purif. technol.": "separation and purification technology",
    "catal today": "catalysis today",
    "catal. today": "catalysis today",
    "green chem": "green chemistry",
    "green energy environ": "green energy & environment",
    "npj comput mater": "npj computational materials",
    "npj quantum inf": "npj quantum information",
    "npj 2d mater appl": "npj 2d materials and applications",
    "sci china chem": "science china chemistry",
    "sci china mater": "science china materials",
    "sci china phys mech astron": "science china physics mechanics & astronomy",
    "sci china technol sci": "science china technological sciences",
    "frontiers in chemistry": "frontiers in chemistry",
    "frontiers in materials": "frontiers in materials",
    "frontiers in physics": "frontiers in physics",
    "frontiers in energy research": "frontiers in energy research",
    "frontiers in chemistry": "frontiers in chemistry",
    "front phys": "frontiers of physics",
    "front. phys.": "frontiers of physics",
    "proc natl acad sci": "proceedings of the national academy of sciences",
    "proc. natl. acad. sci.": "proceedings of the national academy of sciences",
    "embo j": "embo journal",
    "embo reports": "embo reports",
    "mol biol evol": "molecular biology and evolution",
    "plos genet": "plos genetics",
    "plos biol": "plos biology",
    "plos comput biol": "plos computational biology",
    "plos pathogens": "plos pathogens",
    "plos one": "plos one",
    "j clin invest": "journal of clinical investigation",
    "jci": "journal of clinical investigation",
    "j clin oncol": "journal of clinical oncology",
    "jco": "journal of clinical oncology",
    "lancet": "lancet",
    "lancet oncol": "lancet oncology",
    "lancet neurol": "lancet neurology",
    "lancet infect dis": "lancet infectious diseases",
    "lancet diabetes endocrinol": "lancet diabetes & endocrinology",
    "circulation": "circulation",
    "circulation res": "circulation research",
    "circul res": "circulation research",
    "j am coll cardiol": "journal of the american college of cardiology",
    "jacc": "journal of the american college of cardiology",
    "nat rev phys": "nature reviews physics",
    "nat rev mater": "nature reviews materials",
    "nat rev chem": "nature reviews chemistry",
    "nat rev genet": "nature reviews genetics",
    "nat rev immunol": "nature reviews immunology",
    "nat rev neurosci": "nature reviews neuroscience",
    "trends cogn sci": "trends in cognitive neurosciences",
    "trends cognit neurosci": "trends in cognitive neurosciences",
    "csh perspect biol": "cold spring harbor perspectives in biology",
    "csh perspect biol": "cold spring harbor perspectives in biology",
    "cold spring harbor perspect biol": "cold spring harbor perspectives in biology",
    "quarterly review of biology": "quarterly review of biology",
    "biol rev": "biological reviews",
    "biol. rev.": "biological reviews",
}


IF_TOLERANCE_RATIO = 0.5


def get_journal_if_record(journal_name: str) -> Optional[JournalIFRecord]:
    """根据期刊名称获取IF记录"""
    if not journal_name:
        return None

    normalized = _normalize_journal_name(journal_name)
    if not normalized:
        return None

    if normalized in JOURNAL_IF_DATABASE:
        return JOURNAL_IF_DATABASE[normalized]

    alias_key = JOURNAL_ALIASES.get(normalized)
    if alias_key and alias_key in JOURNAL_IF_DATABASE:
        return JOURNAL_IF_DATABASE[alias_key]

    for key in JOURNAL_IF_DATABASE:
        if key in normalized or normalized in key:
            return JOURNAL_IF_DATABASE[key]

    return None


def validate_if_for_journal(journal_name: str, if_value: float) -> tuple[bool, str]:
    """
    验证IF值对于给定期刊是否合理

    Returns:
        (is_valid, reason)
    """
    if if_value <= 0:
        return False, "IF must be positive"

    if if_value > 200:
        return False, f"IF={if_value} is unrealistically high (>200)"

    record = get_journal_if_record(journal_name)
    if record is None:
        if if_value > 50:
            return False, f"IF={if_value} is too high for unknown journal (max reasonable ~50)"
        if if_value < 0.1:
            return False, f"IF={if_value} is too low"
        return True, "Journal not in database, but IF is within reasonable range"

    expected_if = record.if_value
    min_if = expected_if * (1 - IF_TOLERANCE_RATIO)
    max_if = expected_if * (1 + IF_TOLERANCE_RATIO)

    if not (min_if <= if_value <= max_if):
        return False, f"IF={if_value} is outside expected range [{min_if:.1f}, {max_if:.1f}] for {record.name}"

    return True, f"IF={if_value} is valid for {record.name} (expected ~{expected_if})"


def _normalize_journal_name(name: str) -> Optional[str]:
    """标准化期刊名称"""
    if not name:
        return None

    normalized = str(name).lower().strip()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"[^\w\s&-]", "", normalized)
    normalized = re.sub(r"[\s&-]+", " ", normalized).strip()
    return normalized or None


logger = logging.getLogger(__name__)

_VERSION_FILE = Path.home() / ".paperinsight" / "if_database_version.json"


def get_current_if_year() -> int:
    """获取当前应该使用的IF年份（通常是去年，因为今年数据还未发布）"""
    current_year = datetime.now().year
    return current_year - 1


def _get_stored_version() -> dict:
    """获取存储的版本信息"""
    if _VERSION_FILE.exists():
        try:
            return json.loads(_VERSION_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_version_info(year: int, db_year: int) -> None:
    """保存版本信息"""
    _VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        _VERSION_FILE.write_text(json.dumps({
            "current_year": year,
            "db_year": db_year,
            "checked_at": str(Path(__file__).stat().st_mtime)
        }, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to save version info: {e}")


def check_and_report_if_year_updates() -> tuple[int, bool]:
    """
    Check IF year and report if update is needed

    Returns:
        (current_if_year, needs_update)
    """
    current_year = get_current_if_year()
    stored = _get_stored_version()

    if not stored:
        logger.info(f"IF database first use. Current year: {current_year}, DB year: {current_year}")
        _save_version_info(current_year, current_year)
        return current_year, True

    stored_current = stored.get("current_year", 0)
    stored_db_year = stored.get("db_year", 0)

    if current_year != stored_current:
        logger.info(f"Year changed: {stored_current} -> {current_year}, recommend updating IF database")
        _save_version_info(current_year, stored_db_year)
        return current_year, True

    if stored_db_year != current_year:
        logger.warning(f"IF database year ({stored_db_year}) does not match current year ({current_year}), update needed!")
        return current_year, True

    logger.info(f"IF database is up-to-date (year: {current_year}), no update needed")
    return current_year, False


def get_database_year() -> int:
    """获取数据库中IF数据的年份"""
    if JOURNAL_IF_DATABASE:
        first_record = next(iter(JOURNAL_IF_DATABASE.values()), None)
        if first_record:
            return first_record.if_year
    return get_current_if_year()


CURRENT_IF_YEAR = get_current_if_year()
DATABASE_YEAR = get_database_year()
_NEEDS_UPDATE = DATABASE_YEAR != CURRENT_IF_YEAR

if _NEEDS_UPDATE:
    logger.warning(
        f"IF database ({DATABASE_YEAR}) does not match current year ({CURRENT_IF_YEAR}). "
        f"Please update the data in journal_if_database.py to year {CURRENT_IF_YEAR}."
    )
else:
    logger.info(f"IF database is up-to-date (year: {CURRENT_IF_YEAR})")
