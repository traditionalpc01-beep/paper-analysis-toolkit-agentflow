"""
测试优化的影响因子获取器
"""

import pytest
from pathlib import Path
import tempfile

from paperinsight.web.optimized_if_fetcher import OptimizedImpactFactorFetcher
from paperinsight.web.if_cache import ImpactFactorCache
from paperinsight.web.impact_factor_fetcher import ImpactFactorLookupResult


class TestOptimizedImpactFactorFetcher:
    """测试优化的影响因子获取器"""
    
    @pytest.fixture
    def temp_cache_file(self):
        """创建临时缓存文件"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            yield Path(f.name)
    
    @pytest.fixture
    def cache(self, temp_cache_file):
        """创建缓存实例"""
        return ImpactFactorCache(cache_file=temp_cache_file, expiry_days=30)
    
    @pytest.fixture
    def fetcher(self, temp_cache_file):
        """创建优化的获取器实例"""
        return OptimizedImpactFactorFetcher(
            timeout=30,
            max_workers=2,
            max_retries=2,
            cache_expiry_days=30,
            qianwen_api_key=None,
            kimi_api_key=None,
            enable_cache=True,
        )
    
    @pytest.fixture
    def fetcher_with_temp_cache(self, temp_cache_file):
        """创建使用临时缓存的获取器实例"""
        # 创建临时缓存实例
        temp_cache = ImpactFactorCache(cache_file=temp_cache_file, expiry_days=30)
        
        # 创建获取器并注入临时缓存
        from paperinsight.web.optimized_if_fetcher import OptimizedImpactFactorFetcher
        fetcher = OptimizedImpactFactorFetcher.__new__(OptimizedImpactFactorFetcher)
        fetcher.timeout = 30
        fetcher.max_workers = 2
        fetcher.max_retries = 2
        fetcher.enable_cache = True
        fetcher.cache = temp_cache
        fetcher.letpub_fetcher = None  # 不需要实际的网络请求
        fetcher.crossref_fetcher = None
        fetcher.qianwen_fetcher = None
        fetcher.kimi_fetcher = None
        
        return fetcher
    
    def test_cache_basic_operations(self, cache):
        """测试缓存基本操作"""
        # 测试设置和获取
        cache.set(
            journal_name="Nature",
            impact_factor=50.5,
            source_name="TEST",
            source_url="https://test.com",
            year=2024,
        )
        
        result = cache.get("Nature")
        assert result is not None
        assert result.impact_factor == 50.5
        assert result.source_name == "TEST"
        assert result.year == 2024
        
        # 测试不存在的期刊
        result = cache.get("NonExistent Journal")
        assert result is None
    
    def test_cache_preload(self, cache):
        """测试缓存预加载"""
        cache_dict = {
            "Nature": 50.5,
            "Science": 44.7,
            "Cell": 45.5,
        }
        
        cache.preload_from_dict(cache_dict)
        
        for journal_name, expected_if in cache_dict.items():
            result = cache.get(journal_name)
            assert result is not None
            assert result.impact_factor == expected_if
            assert result.source_name == "PRELOADED"
    
    def test_cache_stats(self, cache):
        """测试缓存统计"""
        cache.set("Nature", 50.5, "TEST", "https://test.com", 2024)
        cache.set("Science", 44.7, "TEST", "https://test.com", 2024)
        
        stats = cache.get_stats()
        assert stats["total"] >= 2
        assert stats["valid"] >= 2
        assert "cache_file" in stats
        assert "expiry_days" in stats
    
    def test_cache_clear_expired(self, cache):
        """测试清除过期缓存"""
        # 设置一个已过期的缓存
        cache.set(
            journal_name="Test Journal",
            impact_factor=10.0,
            source_name="TEST",
            source_url="https://test.com",
            expiry_days=-1,  # 已过期
        )
        
        # 清除过期缓存
        deleted = cache.clear_expired()
        assert deleted >= 1
        
        # 验证已清除
        result = cache.get("Test Journal")
        assert result is None
    
    def test_fetcher_initialization(self, fetcher):
        """测试获取器初始化"""
        assert fetcher.timeout == 30
        assert fetcher.max_workers == 2
        assert fetcher.max_retries == 2
        assert fetcher.cache is not None
    
    def test_fetcher_cache_hit(self, fetcher, cache):
        """测试缓存命中"""
        # 预先设置缓存
        cache.set("Nature", 50.5, "PRELOADED", "https://test.com", 2024)

        # 查询应该从本地数据库获取（因为Nature在本地数据库中）
        result = fetcher.lookup(
            paper_title="Test Paper",
            journal_name="Nature",
        )

        assert result.status == "OK"
        assert result.impact_factor == 50.5
        # 本地数据库优先级高于缓存
        assert result.source_name in ["LOCAL_DATABASE", "CACHE_PRELOADED"]

    def test_fetcher_cache_miss(self, fetcher):
        """测试缓存未命中"""
        # 查询一个不在本地数据库中的期刊
        result = fetcher.lookup(
            paper_title="Test Paper",
            journal_name="NonExistent Journal 12345",
        )

        # 应该尝试查询，但由于没有API key，最终失败
        assert result.status in ["NOT_FOUND", "ERROR"]

    def test_fetcher_lookup_many(self, fetcher, cache):
        """测试批量查询"""
        # 预先设置一些缓存
        cache.set("Nature", 50.5, "PRELOADED", "https://test.com", 2024)
        cache.set("Science", 44.7, "PRELOADED", "https://test.com", 2024)

        items = [
            ("Paper 1", "Nature"),
            ("Paper 2", "Science"),
            ("Paper 3", "NonExistent"),
        ]

        results = fetcher.lookup_many(items, delay=0.1)

        assert len(results) == 3
        # 前两个应该从本地数据库获取（因为在本地数据库中）
        assert results[0].status == "OK"
        assert results[1].status == "OK"
        # 第三个应该失败
        assert results[2].status in ["NOT_FOUND", "ERROR"]
    
    def test_fetcher_cache_stats(self, fetcher):
        """测试获取器缓存统计"""
        stats = fetcher.get_cache_stats()
        assert "enabled" in stats
        if stats["enabled"]:
            assert "total" in stats
            assert "valid" in stats
    
    def test_fetcher_clear_cache(self, fetcher_with_temp_cache):
        """测试清除缓存"""
        # 设置一些缓存（使用fetcher的cache）
        fetcher_with_temp_cache.cache.set("Nature", 50.5, "TEST", "https://test.com", 2024)
        fetcher_with_temp_cache.cache.set("Science", 44.7, "TEST", "https://test.com", 2024)
        
        # 清除所有缓存（传入False表示清除所有，不只是过期的）
        deleted = fetcher_with_temp_cache.clear_cache(expired_only=False)
        assert deleted >= 2
        
        # 验证已清除
        stats = fetcher_with_temp_cache.get_cache_stats()
        assert stats["valid"] == 0
    
    def test_fetcher_context_manager(self, temp_cache_file):
        """测试上下文管理器"""
        with OptimizedImpactFactorFetcher(
            timeout=30,
            cache_expiry_days=30,
            enable_cache=True,
        ) as fetcher:
            assert fetcher is not None
            stats = fetcher.get_cache_stats()
            assert stats["enabled"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
