#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
通用网页爬虫 - 自动检测标题、URL和日期
"""
import asyncio
import re
from datetime import datetime
from typing import Dict, List, Tuple
import yaml
import aiohttp
from bs4 import BeautifulSoup
from dateutil import parser
import logging
from models import Database
import warnings
import pymysql

# 禁用MySQL的重复条目警告
warnings.filterwarnings('ignore', category=pymysql.Warning)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class UniversalCrawler:
    def __init__(self, url: str, selector: str = None, exclude=None, headers: Dict = None):
        self.url = url
        self.selector = selector
        self.exclude = exclude if exclude else []
        self.headers = headers or {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }

    async def fetch_page(self) -> str:
        """获取网页内容"""
        async with aiohttp.ClientSession() as session:
            async with session.get(self.url, headers=self.headers) as response:
                if response.status != 200:
                    raise Exception(f"HTTP {response.status}: {self.url}")
                return await response.text()

    def _is_likely_title(self, text: str) -> bool:
        """判断文本是否可能是标题"""
        if not text or len(text.strip()) < 4:  # 标题通常不会太短
            return False
        # 标题通常不会太长
        if len(text.strip()) > 100:
            return False
        # 标题通常不会是纯数字
        if text.strip().isdigit():
            return False
        return True

    def _is_likely_date(self, text: str) -> bool:
        """判断文本是否可能是日期"""
        # 常见的日期格式模式
        date_patterns = [
            r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?',  # 2024-01-01 或 2024年01月01日
            r'\d{4}\.\d{1,2}\.\d{1,2}',              # 2024.01.01
            r'\d{2}/\d{2}/\d{4}',                    # 01/01/2024
        ]
        
        text = text.strip()
        # 检查是否匹配任何日期模式
        for pattern in date_patterns:
            if re.search(pattern, text):
                return True
                
        # 尝试解析日期
        try:
            parser.parse(text)
            return True
        except:
            return False
        
        return False

    def _normalize_url(self, url: str) -> str:
        """标准化URL"""
        if not url:
            return ""
        
        # 如果是相对路径，转换为绝对路径
        if url.startswith('/'):
            from urllib.parse import urlparse
            parsed = urlparse(self.url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            return base_url + url
        
        # 如果不是http开头，且不是相对路径，可能是省略了协议
        if not url.startswith(('http://', 'https://')):
            return f"http://{url}"
            
        return url

    def _should_exclude(self, tag) -> bool:
        """
        判断元素是否应该被排除
        使用更严格和直接的方式检查元素及其父元素
        """
        if not tag or not hasattr(tag, 'attrs'):
            return False

        def check_element(element):
            if not element or not hasattr(element, 'attrs'):
                return False

            for rule in self.exclude:
                if not isinstance(rule, dict):
                    continue

                # 检查class
                if 'class' in rule:
                    element_classes = element.get('class', [])
                    if isinstance(element_classes, str):
                        element_classes = element_classes.split()
                    rule_classes = rule['class'].split()
                    if all(cls in element_classes for cls in rule_classes):
                        logger.debug(f"排除元素: 匹配class规则 {rule['class']}")
                        return True

                # 检查id
                if 'id' in rule and element.get('id') == rule['id']:
                    logger.debug(f"排除元素: 匹配id规则 {rule['id']}")
                    return True

                # 检查特定属性
                if 'attr' in rule:
                    attr_name = rule['attr'].get('name')
                    attr_value = rule['attr'].get('value')
                    if attr_name and attr_value:
                        if element.get(attr_name) == attr_value:
                            logger.debug(f"排除元素: 匹配属性规则 {attr_name}={attr_value}")
                            return True

                # 检查文本内容
                if 'text' in rule:
                    element_text = element.get_text(strip=True)
                    if rule['text'] in element_text:
                        logger.debug(f"排除元素: 匹配文本规则 {rule['text']}")
                        return True

            return False

        # 检查当前元素
        if check_element(tag):
            return True

        # 检查所有父元素（直到最多5层）
        current = tag.parent
        depth = 0
        while current and depth < 5:
            if check_element(current):
                return True
            current = current.parent
            depth += 1

        return False

    def _extract_items(self, soup: BeautifulSoup) -> List[Tuple[str, str, str]]:
        """提取页面中的标题、URL和日期"""
        items = []
        
        try:
            if self.selector:
                containers = soup.select(self.selector)
            else:
                containers = soup.find_all(['li', 'div', 'article'])
            
            if not containers:
                logger.warning(f"网站 {self.url}: 未找到任何内容")
                return items

            # 排除指定class、id和url的内容
            if self.exclude:
                containers = [c for c in containers if not self._should_exclude(c)]

            for container in containers:
                title = None
                url = None
                date = None

                # 提取链接和标题
                link = container.find('a')
                if link:
                    url = link.get('href', '')
                    title = link.get_text(strip=True)

                # 提取日期
                date_text = None
                date_element = container.find(class_=lambda x: x and any(keyword in str(x).lower() for keyword in ['date', 'time', 'pub', '时间', '日期']))
                if date_element:
                    date_text = date_element.get_text(strip=True)
                else:
                    # 尝试从文本中提取日期
                    text = container.get_text(strip=True)
                    date_matches = re.findall(r'\d{4}[-年/]\d{1,2}[-月/]\d{1,2}', text)
                    if date_matches:
                        date_text = date_matches[0]

                if date_text:
                    # 统一日期格式
                    date_text = re.sub(r'[年月]', '-', date_text).replace('日', '')
                    date = date_text.strip('-')

                if title and url:
                    items.append((title, url, date))

            if items:
                logger.info(f"网站 {self.url}: 成功提取 {len(items)} 条数据")
            else:
                logger.warning(f"网站 {self.url}: 未能提取到有效数据")

        except Exception as e:
            logger.error(f"网站 {self.url}: 提取内容时出错 - {str(e)}")

        return items

    async def crawl(self) -> List[Dict]:
        """执行爬取"""
        try:
            html = await self.fetch_page()
            soup = BeautifulSoup(html, 'html.parser')
            
            items = self._extract_items(soup)
            
            results = []
            for title, url, date in items:
                results.append({
                    'title': title,
                    'url': url,
                    'date': date
                })
            
            return results
            
        except Exception as e:
            logger.error(f"爬取失败: {str(e)}")
            return []

class CrawlerManager:
    def __init__(self, config_file: str = 'config.yaml'):
        self.config_file = config_file
        self.config = None
        self.db = None

    def load_config(self):
        """加载配置文件"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f)
            logger.info("配置文件加载成功")
        except Exception as e:
            logger.error(f"加载配置文件失败: {str(e)}")
            raise

    async def init_database(self):
        """初始化数据库连接"""
        try:
            # 创建数据库实例
            self.db = Database(self.config['database'])
            await self.db.connect()
            
            # 为每个网站创建数据表
            for website in self.config['websites']:
                await self.db.create_table_for_website(website['name'])
        except Exception as e:
            logger.error(f"初始化数据库失败: {str(e)}")
            if self.db:
                await self.db.close()
            raise

    async def crawl_all(self):
        """爬取所有配置的网站"""
        for site in self.config['websites']:
            logger.info(f"开始爬取网站: {site['name']}")
            crawler = UniversalCrawler(site['url'], site.get('selector'), site.get('exclude'))
            results = await crawler.crawl()
            
            if results:
                logger.info(f"成功爬取 {site['name']} 的 {len(results)} 条数据")
                # 保存到数据库
                await self.db.save_articles(site['name'], results)
            else:
                logger.warning(f"网站 {site['name']} 未爬取到数据")

    async def run(self):
        """运行爬虫管理器"""
        try:
            self.load_config()
            await self.init_database()
            await self.crawl_all()
        finally:
            if self.db:
                await self.db.close()

async def main():
    """主函数"""
    manager = CrawlerManager()
    await manager.run()

if __name__ == "__main__":
    asyncio.run(main()) 