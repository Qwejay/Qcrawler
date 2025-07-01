import aiomysql
import logging
from datetime import datetime
from typing import List, Dict

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, config):
        self.host = config['host']
        self.port = config['port']
        self.user = config['user']
        self.password = config['password']
        self.db_name = config['db_name']
        self.charset = config['charset']
        self.pool = None

    async def connect(self):
        """连接数据库"""
        try:
            # 创建数据库连接池
            self.pool = await aiomysql.create_pool(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                db=self.db_name,
                charset=self.charset,
                autocommit=True
            )
            await self.create_database()
        except Exception as e:
            logger.error(f"数据库连接失败: {str(e)}")
            raise

    async def create_database(self):
        """创建数据库"""
        try:
            # 创建一个临时连接来创建数据库
            conn = await aiomysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password
            )
            try:
                async with conn.cursor() as cursor:
                    # 禁用警告
                    await cursor.execute("SET sql_notes = 0")
                    await cursor.execute(f"CREATE DATABASE IF NOT EXISTS {self.db_name}")
                    await cursor.execute("SET sql_notes = 1")
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"创建数据库失败: {str(e)}")
            raise

    async def create_table(self, table_name: str):
        """创建数据表"""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # 禁用警告
                    await cursor.execute("SET sql_notes = 0")
                    
                    await cursor.execute(f"""
                        CREATE TABLE IF NOT EXISTS {table_name} (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            title TEXT NOT NULL,
                            url VARCHAR(255) NOT NULL,
                            pub_date DATE,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE KEY unique_url (url)
                        )
                    """)
                    
                    # 恢复警告
                    await cursor.execute("SET sql_notes = 1")
        except Exception as e:
            logger.error(f"创建表 {table_name} 失败: {str(e)}")
            raise

    async def create_table_for_website(self, website_name: str):
        """为特定网站创建数据表"""
        await self.create_table(website_name.lower())

    async def create_tables(self, website_names: list):
        """创建所有网站的数据表"""
        for name in website_names:
            await self.create_table_for_website(name)

    async def save_articles(self, table_name: str, articles: List[Dict]):
        """保存文章数据，只统计真正新增的条数"""
        if not articles:
            return

        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # 插入前的总行数
                    await cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    before_count = (await cursor.fetchone())[0]

                    # 禁用警告
                    await cursor.execute("SET sql_notes = 0")
                    for article in articles:
                        await cursor.execute(
                            f"INSERT IGNORE INTO {table_name} (title, url, pub_date) VALUES (%s, %s, %s)",
                            (article['title'], article['url'], article.get('date'))
                        )
                    await conn.commit()
                    await cursor.execute("SET sql_notes = 1")

                    # 插入后的总行数
                    await cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    after_count = (await cursor.fetchone())[0]
                    new_count = after_count - before_count
                    logger.info(f"{table_name}: 新增 {new_count} 条数据")
        except Exception as e:
            logger.error(f"保存数据到表 {table_name} 失败: {str(e)}")
            raise

    async def close(self):
        """关闭数据库连接池"""
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()
            logger.info("数据库连接池已关闭") 