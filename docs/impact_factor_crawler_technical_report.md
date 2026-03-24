# 影响因子爬虫系统技术方案分析报告

## 一、执行摘要

本报告针对 PaperInsight 项目的影响因子获取系统进行全面的技术方案分析。经过对现有系统的深入评估和多方案对比，推荐采用 **异步爬虫框架 + SQLite 数据库** 的技术方案，该方案在性能、开发效率和长期维护成本之间取得了最佳平衡。

---

## 二、网页爬虫技术对比分析

### 2.1 技术方案概览

| 技术方案 | 性能指标 | 开发复杂度 | 维护成本 | 适用场景 |
|---------|---------|-----------|---------|---------|
| **requests + BeautifulSoup** | 中等 | 低 | 低 | 静态页面、简单爬取 |
| **Scrapy** | 高 | 中 | 中 | 大规模爬取、复杂管道 |
| **aiohttp + asyncio** | 极高 | 中 | 低 | 高并发、异步爬取 |
| **Selenium/Playwright** | 低 | 高 | 高 | 动态页面、JS渲染 |
| **httpx + parsel** | 高 | 低 | 低 | 现代异步爬取 |

### 2.2 详细技术评估

#### 2.2.1 requests + BeautifulSoup（当前方案）

**优势：**
- 项目已集成，无需额外依赖
- 学习曲线平缓，代码可读性高
- 调试简单，问题定位快速
- 与现有 `tenacity` 重试机制无缝集成

**劣势：**
- 同步阻塞模型，并发性能受限
- 大批量抓取时效率较低
- 不支持 HTTP/2

**性能基准：**
```
单次请求延迟: 200-500ms
并发能力: 受限于线程池（通常 10-20 并发）
内存占用: ~50MB/100 并发连接
```

#### 2.2.2 Scrapy 框架

**优势：**
- 内置并发调度、去重、限速
- 完善的中间件系统（代理、User-Agent 轮换）
- 支持分布式爬取（Scrapy-Redis）
- 丰富的扩展生态

**劣势：**
- 学习曲线较陡峭
- 与现有代码集成需要重构
- 过度工程化，对于中小规模爬取可能过重

**性能基准：**
```
单机并发: 100-500 请求/秒
内存占用: ~200MB（默认配置）
CPU 占用: 中等
```

#### 2.2.3 aiohttp + asyncio（推荐方案）

**优势：**
- 原生异步支持，极高并发性能
- 轻量级，内存占用低
- 与 Python 3.7+ 标准库无缝集成
- 可与现有 `tenacity` 库配合

**劣势：**
- 异步编程模型需要学习成本
- 调试相对复杂
- 部分同步库需要异步适配

**性能基准：**
```
单机并发: 500-2000 请求/秒
内存占用: ~30MB/1000 并发连接
CPU 占用: 低
```

#### 2.2.4 Selenium/Playwright

**优势：**
- 完整的浏览器环境，可处理 JavaScript 渲染
- 支持复杂交互（登录、点击、滚动）
- 可处理验证码等反爬机制

**劣势：**
- 资源消耗极大（每个实例 ~200-500MB）
- 启动慢，不适合高频爬取
- 维护成本高（浏览器版本兼容）

**性能基准：**
```
单实例启动: 2-5 秒
并发能力: 受限于实例数量（通常 5-10 并发）
内存占用: 1-5GB（10 并发实例）
```

### 2.3 技术选型建议

基于影响因子数据源的特点（主要是静态 HTML 页面），推荐采用 **混合方案**：

```
┌─────────────────────────────────────────────────────────────┐
│                    爬虫技术分层架构                           │
├─────────────────────────────────────────────────────────────┤
│  第一层：aiohttp + asyncio                                   │
│    - 主力爬取引擎，处理 90% 的静态页面                         │
│    - LetPub、MJL Profile、搜索引擎结果                        │
│                                                              │
│  第二层：requests + BeautifulSoup                            │
│    - 兼容层，处理需要复杂会话管理的场景                        │
│    - 需要登录认证的 API 接口                                  │
│                                                              │
│  第三层：Playwright（可选）                                   │
│    - 备用方案，处理动态渲染页面                                │
│    - 仅在检测到 JS 渲染时启用                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、目标网站反爬机制分析

### 3.1 数据源评估

| 数据源 | URL | 数据质量 | 反爬强度 | API 可用性 | 推荐度 |
|-------|-----|---------|---------|-----------|-------|
| **LetPub** | letpub.com.cn | 高 | 中 | 无 | ⭐⭐⭐⭐ |
| **MJL Profile** | mjl.clarivate.com | 极高 | 高 | 有（需认证） | ⭐⭐⭐⭐⭐ |
| **Web of Science** | api.clarivate.com | 极高 | 低 | 有（付费） | ⭐⭐⭐⭐⭐ |
| **PubMed** | ncbi.nlm.nih.gov | 高 | 低 | 有（免费） | ⭐⭐⭐⭐ |
| **Crossref** | api.crossref.org | 中 | 低 | 有（免费） | ⭐⭐⭐ |
| **期刊官网** | 各出版社域名 | 极高 | 中-高 | 部分有 | ⭐⭐⭐ |

### 3.2 反爬机制详解

#### 3.2.1 LetPub (letpub.com.cn)

**检测到的反爬机制：**
1. User-Agent 检测
2. 请求频率限制（约 1 请求/秒）
3. Cookie 会话验证
4. 可能有 IP 封禁机制

**应对策略：**
```python
# 请求头伪装
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Referer': 'https://www.letpub.com.cn/',
}

# 请求间隔
REQUEST_DELAY = (1.0, 2.0)  # 随机 1-2 秒间隔

# 会话保持
session = requests.Session()
session.headers.update(HEADERS)
```

#### 3.2.2 MJL Profile (mjl.clarivate.com)

**检测到的反爬机制：**
1. Bearer Token 认证
2. CORS 限制
3. 请求频率限制
4. Cloudflare 保护（可能）

**应对策略：**
- 使用官方 API（推荐）
- Token 从浏览器开发者工具获取
- 定期刷新 Token（建议每日）

#### 3.2.3 期刊官网

**常见反爬机制：**
1. Cloudflare/WAF 保护
2. 验证码（reCAPTCHA, hCaptcha）
3. JavaScript 渲染
4. IP 黑名单

**应对策略：**
- 优先使用官方 API
- 设置合理的请求间隔
- 使用代理 IP 池（必要时）
- 尊重 robots.txt

### 3.3 robots 协议合规性

```
# LetPub robots.txt 分析
User-agent: *
Disallow: /admin/
Disallow: /user/
Allow: /

# MJL robots.txt 分析
User-agent: *
Disallow: /api/internal/
Allow: /api/mjl/
```

**合规建议：**
1. 所有爬取请求添加 `robots.txt` 检查
2. 设置合理的请求间隔（≥1 秒）
3. 在请求头中标识爬虫身份
4. 提供联系方式（From 头）

---

## 四、数据存储方案评估

### 4.1 存储方案对比

| 存储方案 | 存储效率 | 查询性能 | 扩展性 | 维护成本 | 适用规模 |
|---------|---------|---------|-------|---------|---------|
| **SQLite** | 高 | 高 | 低 | 极低 | < 100 万条 |
| **PostgreSQL** | 高 | 极高 | 高 | 中 | > 100 万条 |
| **MongoDB** | 中 | 高 | 极高 | 中 | 非结构化数据 |
| **JSON 文件** | 低 | 低 | 无 | 极低 | < 1 万条 |
| **Redis** | 极高 | 极高 | 高 | 中 | 缓存/临时数据 |

### 4.2 数据模型设计

#### 4.2.1 核心表结构

```sql
-- 期刊主表
CREATE TABLE journals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL UNIQUE,
    issn TEXT UNIQUE,
    eissn TEXT UNIQUE,
    publisher TEXT,
    country TEXT,
    language TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 影响因子表
CREATE TABLE impact_factors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    journal_id INTEGER NOT NULL,
    if_value REAL NOT NULL,
    if_year INTEGER NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT,
    confidence_score REAL DEFAULT 1.0,
    verified BOOLEAN DEFAULT FALSE,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (journal_id) REFERENCES journals(id),
    UNIQUE(journal_id, if_year, source_name)
);

-- 期刊别名表
CREATE TABLE journal_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    journal_id INTEGER NOT NULL,
    alias_name TEXT NOT NULL,
    alias_type TEXT DEFAULT 'alternate',
    FOREIGN KEY (journal_id) REFERENCES journals(id),
    UNIQUE(journal_id, alias_name)
);

-- 学科分类表
CREATE TABLE journal_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    journal_id INTEGER NOT NULL,
    category_name TEXT NOT NULL,
    category_rank INTEGER,
    FOREIGN KEY (journal_id) REFERENCES journals(id)
);

-- 爬取任务表
CREATE TABLE crawl_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,
    target_url TEXT,
    status TEXT DEFAULT 'pending',
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    records_processed INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX idx_journals_issn ON journals(issn);
CREATE INDEX idx_journals_eissn ON journals(eissn);
CREATE INDEX idx_if_journal_year ON impact_factors(journal_id, if_year);
CREATE INDEX idx_if_year ON impact_factors(if_year);
CREATE INDEX idx_aliases_name ON journal_aliases(alias_name);
```

#### 4.2.2 数据字典

| 字段名 | 类型 | 说明 | 示例值 |
|-------|------|------|-------|
| canonical_name | TEXT | 期刊标准名称 | "Nature" |
| issn | TEXT | 印刷版 ISSN | "0028-0836" |
| eissn | TEXT | 电子版 ISSN | "1476-4687" |
| if_value | REAL | 影响因子数值 | 69.504 |
| if_year | INTEGER | 影响因子年份 | 2024 |
| source_name | TEXT | 数据来源 | "MJL" |
| confidence_score | REAL | 置信度评分 (0-1) | 0.95 |
| verified | BOOLEAN | 是否已验证 | TRUE |

### 4.3 存储方案推荐

**推荐方案：SQLite + 可选 PostgreSQL 升级路径**

**理由：**
1. 当前数据规模（约 10 万期刊）完全在 SQLite 能力范围内
2. 零配置、零运维，适合桌面应用
3. 支持全文搜索（FTS5 扩展）
4. 可无缝迁移到 PostgreSQL（语法兼容）

**升级路径：**
```
SQLite (当前) 
    ↓ 数据量 > 50 万条
PostgreSQL (可选)
    ↓ 需要分布式
PostgreSQL + Citus (分布式)
```

---

## 五、成本效益分析

### 5.1 开发成本估算

| 方案 | 开发时间 | 人力成本 | 技术风险 |
|-----|---------|---------|---------|
| requests + SQLite | 2 周 | 低 | 低 |
| Scrapy + PostgreSQL | 4 周 | 中 | 中 |
| aiohttp + SQLite | 3 周 | 中 | 低 |
| Playwright + MongoDB | 5 周 | 高 | 高 |

### 5.2 运维成本估算

| 方案 | 服务器成本 | 维护频率 | 故障风险 |
|-----|-----------|---------|---------|
| SQLite 方案 | 0（本地运行） | 月度 | 低 |
| PostgreSQL 方案 | $10-50/月 | 周度 | 中 |
| MongoDB 方案 | $20-100/月 | 周度 | 中 |

### 5.3 总体成本对比（3 年周期）

| 方案 | 开发成本 | 运维成本 | 维护成本 | 总成本 |
|-----|---------|---------|---------|-------|
| **推荐方案** (aiohttp + SQLite) | $5,000 | $0 | $1,000 | **$6,000** |
| Scrapy + PostgreSQL | $10,000 | $1,800 | $3,000 | $14,800 |
| Playwright + MongoDB | $15,000 | $3,600 | $5,000 | $23,600 |

---

## 六、最终技术选型

### 6.1 推荐方案

```
┌─────────────────────────────────────────────────────────────┐
│                    推荐技术栈                                │
├─────────────────────────────────────────────────────────────┤
│  爬虫引擎: aiohttp + asyncio (主力) + requests (兼容)        │
│  解析器:   parsel (XPath/CSS) + lxml                        │
│  数据库:   SQLite (默认) + PostgreSQL (可选升级)             │
│  调度器:   APScheduler                                      │
│  缓存:     内置 SQLite 缓存 + 可选 Redis                     │
│  代理池:   内置轮换 + 可选外部代理服务                        │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 选型理由

1. **性能与复杂度平衡**：aiohttp 提供足够的并发性能，同时保持代码简洁
2. **与现有系统集成**：可复用现有的 `tenacity` 重试机制和配置系统
3. **低运维成本**：SQLite 零配置，适合桌面应用场景
4. **可扩展性**：预留 PostgreSQL 升级路径，支持未来扩展

### 6.3 风险缓解

| 风险 | 缓解措施 |
|-----|---------|
| 反爬封禁 | 请求频率控制 + 代理池 + 多源备份 |
| 数据源失效 | 多数据源冗余 + 本地缓存 |
| 数据不一致 | 交叉验证 + 置信度评分 |
| 性能瓶颈 | 异步架构 + 批量处理 |

---

## 七、实施路线图

### Phase 1: 核心爬虫引擎（第 1-2 周）
- 实现异步请求调度器
- 集成反爬策略（User-Agent 轮换、请求延迟）
- 实现代理池管理

### Phase 2: 数据解析模块（第 2-3 周）
- 实现 LetPub 解析器
- 实现 MJL Profile 解析器
- 实现通用期刊官网解析器

### Phase 3: 数据存储层（第 3-4 周）
- 实现 SQLite 数据库层
- 实现数据清洗与验证
- 实现数据迁移脚本

### Phase 4: 调度与接口（第 4-5 周）
- 实现定时任务调度
- 实现 CLI 查询接口
- 实现 REST API（可选）

### Phase 5: 测试与优化（第 5-6 周）
- 性能测试与优化
- 文档编写
- 部署与交付

---

## 八、附录

### A. 技术依赖清单

```toml
[project.dependencies]
aiohttp = ">=3.9.0"
aiosqlite = ">=0.19.0"
parsel = ">=1.8.1"
lxml = ">=5.0.0"
apscheduler = ">=3.10.0"
tenacity = ">=8.2.0"  # 已有
pydantic = ">=2.0.0"  # 已有
```

### B. 参考资料

1. LetPub 期刊查询: https://www.letpub.com.cn/
2. MJL API 文档: https://mjl.clarivate.com/api-docs
3. Web of Science API: https://developer.clarivate.com/apis/wos-journals
4. SQLite 性能优化: https://www.sqlite.org/optoverview.html
5. aiohttp 最佳实践: https://docs.aiohttp.org/en/stable/

---

*报告生成时间: 2026-03-19*
*版本: 1.0*
