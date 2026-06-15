import redis  # 导入 redis 库
from simhash import Simhash  # 导入 Simhash 用于文本相似度计算
from app.config import settings  # 导入配置
import logging  # 导入日志模块

logger = logging.getLogger(__name__)  # 初始化日志

# 初始化 Redis 客户端
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)  # 连接 Redis，并自动解码响应为字符串

def is_duplicate(url: str, content: str) -> bool:  # 定义查重函数
    """
    基于 URL 或 Simhash 检查文章是否重复。
    """
    try:  # 开启异常捕获
        # 1. URL 级别查重
        if redis_client.sismember("crawled_urls", url):  # 如果 URL 已存在于 Redis 的 Set 中
            return True  # 判定为重复
            
        # 2. 内容 Simhash 级别查重
        if not content:  # 如果内容为空
            return False  # 不判定为重复（可能后续还需要处理）
            
        current_hash = Simhash(content).value  # 计算当前文章内容的 Simhash 整数值
        
        # 获取近期抓取的文章的 Simhash 列表
        recent_hashes = redis_client.lrange("recent_simhashes", 0, -1)  # 从 Redis List 中取出所有近期的哈希值
        for h in recent_hashes:  # 遍历近期的哈希值
            h_val = int(h)  # 转换为整数
            # 计算海明距离 (Hamming distance)
            distance = bin(current_hash ^ h_val).count('1')  # 异或后统计二进制中 1 的个数
            if distance < 3:  # 如果距离小于 3 (经验阈值)，说明内容极度相似
                return True  # 判定为重复
                
        # 如果不重复，则将其加入 Redis 记录中
        redis_client.sadd("crawled_urls", url)  # 将 URL 存入 Set
        redis_client.lpush("recent_simhashes", current_hash)  # 将新的 Simhash 插入 List 头部
        redis_client.ltrim("recent_simhashes", 0, 10000) # 裁剪 List，仅保留最近的 10000 条记录防止内存溢出
        
        return False  # 返回不重复
    except Exception as e:  # 捕获异常
        logger.error(f"Error in deduplication check: {e}")  # 记录异常日志
        # 发生异常时，默认放行 (Fail open)，避免阻断业务
        return False  # 返回不重复
