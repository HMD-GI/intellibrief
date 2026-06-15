import bootstrap  # 初始化项目根路径，保证 test 目录脚本可直接运行
from app.database import SessionLocal
from app.models.article import Article, ArticleStatus

db = SessionLocal()

# 将所有 pending 状态的文章改为 processed
articles = db.query(Article).filter(Article.status == ArticleStatus.pending).all()

if not articles:
    print("❌ 没有找到 pending 状态的文章")
else:
    print(f"找到 {len(articles)} 篇 pending 状态的文章\n")
    
    for article in articles:
        article.status = ArticleStatus.processed
        article.quality_score = 80  # 设置一个较高的质量分数
        if not article.summary:
            article.summary = '{"one_liner": "测试摘要", "key_points": ["要点1", "要点2"]}'
        if not article.topic:
            article.topic = "测试分类"
    
    db.commit()
    print(f"✅ 已将 {len(articles)} 篇文章标记为 processed")
    print("\n现在可以生成简报了！")
    print("在 Swagger UI 中调用: POST /tasks/generate-brief")

db.close()
