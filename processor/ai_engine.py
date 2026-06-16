import json  # 导入 json 模块用于解析 LLM 响应
import logging  # 导入日志模块
from concurrent.futures import ThreadPoolExecutor, as_completed  # 导入线程池，用于并发调用大模型
from typing import List  # 导入 List
from app.models.article import Article  # 导入文章模型
from utils.llm_router import AllLLMKeysFailedError, llm_router  # 导入大模型路由实例和全部 Key 失败异常
from processor.prompts import build_glm_classify_prompt, build_glm_filter_prompt, build_summary_prompt  # 导入统一提示词构造函数

logger = logging.getLogger(__name__)  # 初始化日志
MAX_LLM_WORKERS = 6  # 大模型并发线程数上限，避免一次性压垮 API 限流

def _worker_count(total: int) -> int:  # 根据文章数量计算线程数
    return max(1, min(MAX_LLM_WORKERS, total))  # 至少 1 个线程，最多不超过上限

def _filter_one_article(article: Article) -> tuple[Article, bool, int]:  # 单篇文章筛选，供线程池调用
    first_paragraph = article.content[:500] if article.content else ""  # 取前 500 个字符作为首段内容
    topics = article.topic or "前沿科技, AI"  # 获取主题，若无则使用默认
    prompt = build_glm_filter_prompt(article.title, first_paragraph, topics)  # 从统一提示词文件构建筛选提示词
    messages = [{"role": "user", "content": prompt}]  # 构造消息上下文
    response_text = llm_router.call_llm(
        provider="first",  # 第一步使用 FIRST_LLM_* 配置
        messages=messages,  # 传入上下文
        response_format={"type": "json_object"}  # 强制 JSON
    )
    result = json.loads(response_text)  # 将返回的文本解析为 JSON 字典
    return article, bool(result.get("relevant")), int(result.get("score", 0) or 0)

def _summary_one_article(article: Article) -> tuple[Article, dict]:  # 单篇文章摘要，供线程池调用
    content = article.content[:3000] if article.content else ""  # 截取前 3000 字符，避免 Token 超限
    prompt = build_summary_prompt(content)  # 从统一提示词文件构建摘要提示词
    messages = [{"role": "user", "content": prompt}]  # 构造消息上下文
    response_text = llm_router.call_llm(
        provider="second",  # 第二步使用 SECOND_LLM_* 配置
        messages=messages,  # 传入上下文
        response_format={"type": "json_object"}  # 强制 JSON 格式
    )
    return article, json.loads(response_text)  # 返回文章对象和摘要结果

def _classify_one_article(article: Article) -> tuple[Article, str]:  # 单篇文章分类，供线程池调用
    prompt = build_glm_classify_prompt(article.title, article.tags or "")  # 从统一提示词文件构建分类提示词
    messages = [{"role": "user", "content": prompt}]
    response_text = llm_router.call_llm(provider="third", messages=messages)  # 第三步使用 THIRD_LLM_* 配置
    return article, (response_text or "").strip()

def filter_articles(articles: List[Article]) -> List[Article]:  # 定义文章筛选函数
    """
    第一步：使用第一步模型完成文章筛选和评分。
    """
    filtered = []  # 初始化过滤后的文章列表
    if not articles:
        return filtered
    with ThreadPoolExecutor(max_workers=_worker_count(len(articles))) as executor:
        futures = [executor.submit(_filter_one_article, article) for article in articles]  # 并发提交筛选任务
        for future in as_completed(futures):
            try:
                article, relevant, score = future.result()
                article.quality_score = score  # 主线程写回 ORM 对象
                if relevant and score >= 60:  # 如果判定相关且分数及格 (>=60)
                    filtered.append(article)  # 加入到保留列表中
            except AllLLMKeysFailedError:
                for item in futures:
                    item.cancel()  # 所有 API Key 都失败时取消剩余任务
                raise  # 交由任务层统一结束
            except Exception as e:  # 捕获筛选异常
                logger.error(f"Error filtering article: {e}")  # 记录错误
            
    return filtered  # 返回筛选通过的文章

def generate_summary(article: Article) -> None:  # 定义摘要生成函数
    """
    使用第二步模型生成深度摘要。
    """
    try:  # 开启异常捕获
        target, result = _summary_one_article(article)
        _apply_summary_result(target, result)  # 主线程或兼容调用中写回摘要结果
        
    except AllLLMKeysFailedError:
        raise  # 所有 API Key 都失败时直接中断流程，交由任务层统一结束
    except Exception as e:  # 捕获异常
        logger.error(f"Error generating summary for article {article.id}: {e}")  # 记录错误

def _apply_summary_result(article: Article, result: dict) -> None:  # 将摘要结果写回文章对象
    article.summary = json.dumps({
        "one_liner": result.get("one_liner", ""),  # 提取一句话总结
        "key_points": result.get("key_points", [])  # 提取关键点数组
    }, ensure_ascii=False)  # 禁止 ascii 转义以保留中文
    article.tags = ",".join(result.get("tags", []))  # 将标签数组用逗号拼接为字符串并保存

def generate_summaries(articles: List[Article]) -> None:  # 并发生成摘要
    if not articles:
        return
    with ThreadPoolExecutor(max_workers=_worker_count(len(articles))) as executor:
        futures = [executor.submit(_summary_one_article, article) for article in articles]  # 并发提交摘要任务
        for future in as_completed(futures):
            try:
                article, result = future.result()
                _apply_summary_result(article, result)  # 主线程写回 ORM 对象
            except AllLLMKeysFailedError:
                for item in futures:
                    item.cancel()  # 所有 API Key 都失败时取消剩余任务
                raise
            except Exception as e:
                logger.error(f"Error generating summary: {e}")  # 单篇失败不阻断其他文章

def classify_articles(articles: List[Article]) -> None:  # 使用 GLM 对文章做主题分类（第三步）
    """
    第三步：使用第三步模型对筛选通过的文章做主题分类。
    """
    if not articles:
        return
    with ThreadPoolExecutor(max_workers=_worker_count(len(articles))) as executor:
        futures = [executor.submit(_classify_one_article, article) for article in articles]  # 并发提交分类任务
        for future in as_completed(futures):
            try:
                article, topic = future.result()
                article.topic = topic  # 主线程写回 ORM 对象
            except AllLLMKeysFailedError:
                for item in futures:
                    item.cancel()  # 所有 API Key 都失败时取消剩余任务
                raise  # 所有 API Key 都失败时直接中断流程，交由任务层统一结束
            except Exception as e:
                logger.error(f"Error classifying article: {e}")
