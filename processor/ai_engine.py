import json  # 导入 json 模块用于解析 LLM 响应
import logging  # 导入日志模块
from typing import List  # 导入 List
from app.models.article import Article  # 导入文章模型
from utils.llm_router import AllLLMKeysFailedError, llm_router  # 导入大模型路由实例和全部 Key 失败异常
from processor.prompts import build_glm_classify_prompt, build_glm_filter_prompt, build_summary_prompt  # 导入统一提示词构造函数

logger = logging.getLogger(__name__)  # 初始化日志

def filter_articles(articles: List[Article]) -> List[Article]:  # 定义文章筛选函数
    """
    第一步：使用 GLM 完成文章筛选和评分。
    """
    filtered = []  # 初始化过滤后的文章列表
    for article in articles:  # 遍历传入的文章列表
        try:  # 开启单篇文章处理的异常捕获
            first_paragraph = article.content[:500] if article.content else ""  # 取前 500 个字符作为首段内容
            topics = article.topic or "前沿科技, AI"  # 获取主题，若无则使用默认
            prompt = build_glm_filter_prompt(article.title, first_paragraph, topics)  # 从统一提示词文件构建筛选提示词
            
            messages = [{"role": "user", "content": prompt}]  # 构造消息上下文
            
            # 请求 LLM，强制要求返回 JSON 对象
            response_text = llm_router.call_llm(
                provider='zhipu',  # 使用智谱 (免费快速)
                messages=messages,  # 传入上下文
                response_format={"type": "json_object"}  # 强制 JSON
            )
            
            result = json.loads(response_text)  # 将返回的文本解析为 JSON 字典
            article.quality_score = result.get("score", 0)  # 获取分数，默认 0，并赋给文章对象
            
            if result.get("relevant") and article.quality_score >= 60:  # 如果判定相关且分数及格 (>=60)
                filtered.append(article)  # 加入到保留列表中
                
        except AllLLMKeysFailedError:
            raise  # 所有 API Key 都失败时直接中断流程，交由任务层统一结束
        except Exception as e:  # 捕获筛选异常
            logger.error(f"Error filtering article {article.id}: {e}")  # 记录错误
            
    return filtered  # 返回筛选通过的文章

def generate_summary(article: Article) -> None:  # 定义摘要生成函数
    """
    使用 DeepSeek 生成深度摘要。
    """
    try:  # 开启异常捕获
        content = article.content[:3000] if article.content else ""  # 截取前 3000 字符，避免 Token 超限
        prompt = build_summary_prompt(content)  # 从统一提示词文件构建摘要提示词
        
        messages = [{"role": "user", "content": prompt}]  # 构造消息上下文
        response_text = llm_router.call_llm(
            provider='deepseek',  # 使用 DeepSeek (长文总结能力强)
            messages=messages,  # 传入上下文
            response_format={"type": "json_object"}  # 强制 JSON 格式
        )
        
        result = json.loads(response_text)  # 解析返回的 JSON
        # 将一句话总结和要点打包存入 summary 字段
        article.summary = json.dumps({
            "one_liner": result.get("one_liner", ""),  # 提取一句话总结
            "key_points": result.get("key_points", [])  # 提取关键点数组
        }, ensure_ascii=False)  # 禁止 ascii 转义以保留中文
        article.tags = ",".join(result.get("tags", []))  # 将标签数组用逗号拼接为字符串并保存
        
    except AllLLMKeysFailedError:
        raise  # 所有 API Key 都失败时直接中断流程，交由任务层统一结束
    except Exception as e:  # 捕获异常
        logger.error(f"Error generating summary for article {article.id}: {e}")  # 记录错误

def classify_articles(articles: List[Article]) -> None:  # 使用 GLM 对文章做主题分类（第三步）
    """
    第三步：使用 GLM 对筛选通过的文章做主题分类。
    """
    for article in articles:
        try:
            prompt = build_glm_classify_prompt(article.title, article.tags or "")  # 从统一提示词文件构建分类提示词
            messages = [{"role": "user", "content": prompt}]
            response_text = llm_router.call_llm(provider="zhipu", messages=messages)  # 使用 GLM 分类
            article.topic = (response_text or "").strip()
        except AllLLMKeysFailedError:
            raise  # 所有 API Key 都失败时直接中断流程，交由任务层统一结束
        except Exception as e:
            logger.error(f"Error classifying article {article.id}: {e}")
