from fastapi import APIRouter, BackgroundTasks  # 导入 APIRouter 等组件
from datetime import date  # 导入 date
from scheduler.tasks import crawl_all_sources, ai_process_articles, generate_and_push_brief, run_all_tasks_immediately  # 导入 Celery 任务函数

router = APIRouter(prefix="/tasks", tags=["tasks"])  # 创建任务管理路由实例，前缀 /tasks

@router.post("/crawl")  # 注册触发全量爬虫的 POST 路由
def trigger_crawl():  # 处理函数
    crawl_all_sources.delay(process_inline=True)  # 抓取详情页日期为当天的全部文章并同步入库
    return {"message": "Crawl task triggered (today articles)"}  # 返回触发成功消息

@router.post("/ai-process")  # 注册触发 AI 处理流程的 POST 路由
def trigger_ai_process():  # 处理函数
    ai_process_articles.delay()  # 异步调用 Celery 的 AI 处理任务
    return {"message": "AI process task triggered"}  # 返回触发成功消息

@router.post("/generate-brief")  # 注册触发生成简报的 POST 路由
def trigger_generate_brief():  # 处理函数
    generate_and_push_brief.delay()  # 异步调用 Celery 的简报生成与推送任务
    return {"message": "Generate brief task triggered"}  # 返回触发成功消息

@router.post("/run-all")  # 注册触发完整流水线的 POST 路由
def trigger_run_all():  # 处理函数
    """
    一键触发完整的流水线（测试用）：爬取 -> AI分析 -> 生成简报
    """
    run_all_tasks_immediately.delay()  # 异步调用全流程任务
    return {"message": "Full pipeline task triggered immediately"}  # 返回触发成功消息
