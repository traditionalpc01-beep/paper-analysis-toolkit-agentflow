# 影响因子爬虫系统部署文档

## 一、系统要求

### 1.1 软件要求

| 组件 | 版本要求 |
|------|---------|
| Python | >= 3.9 |
| SQLite | >= 3.35.0 |
| 操作系统 | Windows 10+, macOS 10.15+, Linux |

### 1.2 硬件要求

| 指标 | 最低配置 | 推荐配置 |
|------|---------|---------|
| CPU | 2 核 | 4 核+ |
| 内存 | 2 GB | 4 GB+ |
| 磁盘 | 100 MB | 1 GB+ |

## 二、安装步骤

### 2.1 安装依赖

```bash
# 进入项目目录
cd paper-analysis-toolkit

# 安装依赖
pip install -e .

# 或者手动安装核心依赖
pip install aiohttp>=3.9.0 aiosqlite>=0.19.0 apscheduler>=3.10.0 tenacity>=8.2.0 pydantic>=2.0.0
```

### 2.2 验证安装

```python
from paperinsight.crawler import ImpactFactorQueryAPI, CrawlerConfig

# 创建默认配置
config = CrawlerConfig()
print(f"数据库路径: {config.storage.database_path}")

# 初始化 API
api = ImpactFactorQueryAPI(config)
print("安装成功!")
```

## 三、配置说明

### 3.1 配置文件结构

配置文件支持 JSON 格式，默认配置如下：

```json
{
  "request": {
    "timeout": 30,
    "connect_timeout": 10,
    "max_retries": 3,
    "min_request_delay": 0.5,
    "max_request_delay": 2.0,
    "concurrent_limit": 10
  },
  "proxy": {
    "enabled": false,
    "proxies": [],
    "rotation_strategy": "round_robin"
  },
  "anti_crawler": {
    "enable_random_delay": true,
    "enable_user_agent_rotation": true,
    "respect_robots_txt": true,
    "max_requests_per_domain": 100
  },
  "storage": {
    "database_type": "sqlite",
    "database_path": "~/.paperinsight/impact_factor.db",
    "cache_expiry_days": 30,
    "enable_fts": true
  },
  "scheduler": {
    "enabled": false,
    "update_interval_hours": 24,
    "update_time": "02:00",
    "batch_size": 100
  },
  "data_sources": {
    "letpub": {
      "name": "LetPub",
      "base_url": "https://www.letpub.com.cn/",
      "enabled": true,
      "priority": 1
    },
    "mjl": {
      "name": "MJL Profile",
      "base_url": "https://mjl.clarivate.com/",
      "enabled": true,
      "priority": 2,
      "requires_auth": true,
      "api_key": ""
    }
  }
}
```

### 3.2 加载自定义配置

```python
from pathlib import Path
from paperinsight.crawler import CrawlerConfig, ImpactFactorQueryAPI

# 从文件加载配置
config = CrawlerConfig.from_file(Path("crawler_config.json"))

# 使用自定义配置
api = ImpactFactorQueryAPI(config)
```

### 3.3 数据源配置

#### LetPub（免费）

```python
config.data_sources["letpub"] = DataSourceConfig(
    name="LetPub",
    base_url="https://www.letpub.com.cn/",
    enabled=True,
    priority=1,
    rate_limit=1.0,  # 每秒 1 个请求
)
```

#### MJL Profile（需认证）

```python
config.data_sources["mjl"] = DataSourceConfig(
    name="MJL Profile",
    base_url="https://mjl.clarivate.com/",
    enabled=True,
    priority=2,
    requires_auth=True,
    auth_type="bearer",
    api_key="your_bearer_token",  # 从浏览器获取
)
```

#### Web of Science API（付费）

```python
config.data_sources["wos"] = DataSourceConfig(
    name="Web of Science",
    base_url="https://api.clarivate.com/apis/wos-journals/v1",
    enabled=True,
    priority=3,
    requires_auth=True,
    auth_type="api_key",
    api_key="your_api_key",  # 从 Clarivate 获取
)
```

## 四、代理池配置

### 4.1 启用代理池

```python
from paperinsight.crawler import ProxyConfig

config.proxy = ProxyConfig(
    enabled=True,
    proxies=[
        "http://proxy1.example.com:8080",
        "http://proxy2.example.com:8080",
    ],
    rotation_strategy="round_robin",
    ban_threshold=3,
    ban_duration=300,
)
```

### 4.2 从文件加载代理

```python
# 创建代理列表文件 proxies.txt
# 格式：每行一个代理地址
# http://proxy1.example.com:8080
# http://proxy2.example.com:8080

config.proxy = ProxyConfig(
    enabled=True,
    proxy_file=Path("proxies.txt"),
)
```

## 五、定时任务配置

### 5.1 启用定时更新

```python
from paperinsight.crawler import SchedulerConfig

config.scheduler = SchedulerConfig(
    enabled=True,
    update_interval_hours=24,
    update_time="02:00",  # 凌晨 2 点执行
    batch_size=100,
    max_workers=5,
)
```

### 5.2 运行调度器

```python
import asyncio
from paperinsight.crawler import TaskScheduler, ImpactFactorDatabase

async def run_scheduler():
    scheduler = TaskScheduler(
        config=config.scheduler,
        database=ImpactFactorDatabase(config.storage),
    )
    
    # 启动调度器（阻塞运行）
    scheduler.start()
    
    try:
        # 保持运行
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        scheduler.stop()

asyncio.run(run_scheduler())
```

## 六、数据迁移

### 6.1 从旧缓存迁移

```python
from paperinsight.web.if_cache import ImpactFactorCache as OldCache
from paperinsight.crawler import ImpactFactorDatabase, JournalRecord, ImpactFactorRecord

def migrate_from_old_cache():
    old_cache = OldCache()
    new_db = ImpactFactorDatabase()
    
    # 获取旧缓存统计
    stats = old_cache.get_stats()
    print(f"旧缓存记录数: {stats['total']}")
    
    # 迁移逻辑...
```

### 6.2 从 JSON 文件导入

```python
import json
from paperinsight.crawler import ImpactFactorDatabase, JournalRecord, ImpactFactorRecord

def import_from_json(json_file: str):
    db = ImpactFactorDatabase()
    
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    for item in data:
        # 创建期刊记录
        journal = JournalRecord(
            canonical_name=item["journal_name"],
            issn=item.get("issn"),
            eissn=item.get("eissn"),
        )
        journal.id = db.upsert_journal(journal)
        
        # 创建影响因子记录
        if item.get("impact_factor"):
            if_record = ImpactFactorRecord(
                journal_id=journal.id,
                if_value=item["impact_factor"],
                if_year=item.get("year", 2024),
                source=DataSourceType.LOCAL,
            )
            db.upsert_impact_factor(if_record)
    
    print(f"导入完成: {len(data)} 条记录")
```

## 七、性能优化

### 7.1 数据库优化

```python
# 定期清理数据库碎片
db = ImpactFactorDatabase()
db.vacuum()

# 备份数据库
backup_path = db.backup()
```

### 7.2 并发配置

```python
# 根据机器性能调整并发数
config.request.concurrent_limit = 20  # 提高并发上限
config.scheduler.max_workers = 10     # 提高工作线程数
```

### 7.3 缓存策略

```python
# 延长缓存有效期
config.storage.cache_expiry_days = 90  # 90 天

# 启用全文搜索
config.storage.enable_fts = True
```

## 八、监控与日志

### 8.1 配置日志

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("crawler.log"),
        logging.StreamHandler(),
    ]
)
```

### 8.2 获取统计信息

```python
api = ImpactFactorQueryAPI()
stats = api.get_stats()

print(f"期刊总数: {stats['total_journals']}")
print(f"IF 记录数: {stats['total_if_records']}")
print(f"已验证记录: {stats['verified_records']}")
print(f"按年份分布: {stats['if_by_year']}")
```

## 九、故障排除

### 9.1 常见问题

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| 连接超时 | 网络问题或目标服务器响应慢 | 增加 timeout 值 |
| 请求被拒绝 | 反爬机制触发 | 降低请求频率、启用代理 |
| 数据库锁定 | SQLite 并发限制 | 减少并发数或升级到 PostgreSQL |
| 内存占用高 | 批量任务过大 | 减小 batch_size |

### 9.2 错误代码

| 错误码 | 说明 |
|-------|------|
| `RateLimitException` | 请求频率超限 |
| `BlockedException` | IP 被封禁 |
| `ParseException` | 页面解析失败 |
| `CrawlerException` | 通用爬虫错误 |

## 十、升级指南

### 10.1 版本兼容性

- v1.0.0: 初始版本，支持基本爬取功能
- 后续版本将保持向后兼容

### 10.2 数据库升级

```python
# 数据库模式会自动升级
db = ImpactFactorDatabase()
# 升级会在初始化时自动执行
```

---

*文档版本: 1.0.0*
*更新日期: 2026-03-19*
