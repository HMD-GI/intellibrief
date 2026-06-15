from celery.schedules import crontab  # 导入 crontab 用于定时调度

beat_schedule = {  # 定义 Celery Beat 调度表
    'daily-crawl': {  # 任务名称：每日爬取
        'task': 'scheduler.tasks.crawl_all_sources',  # 对应的任务路径
        'schedule': crontab(hour=2, minute=0),  # 调度时间：每天凌晨 2 点执行
    },
    'daily-ai-process': {  # 任务名称：每日 AI 处理
        'task': 'scheduler.tasks.ai_process_articles',  # 对应的任务路径
        'schedule': crontab(hour=5, minute=0),  # 调度时间：每天凌晨 5 点执行
    },
    'daily-brief-push': {  # 任务名称：每日简报推送
        'task': 'scheduler.tasks.generate_and_push_brief',  # 对应的任务路径
        'schedule': crontab(hour=7, minute=0),  # 调度时间：每天早上 7 点执行
    },
}
