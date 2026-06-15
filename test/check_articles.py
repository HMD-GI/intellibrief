import bootstrap  # 初始化项目根路径，保证 test 目录脚本可直接运行
from app.database import SessionLocal
from app.models.article import Article, ArticleStatus

db = SessionLocal()

# 统计各状态的文章数量
print("📊 文章状态统计:\n")
for status in ArticleStatus:
    count = db.query(Article).filter(Article.status == status).count()
    print(f"  {status.value}: {count} 篇")

print("\n" + "="*60)

# 显示最近处理的文章
processed_articles = db.query(Article).filter(
    Article.status == ArticleStatus.processed
).order_by(Article.id.desc()).limit(10).all()

if processed_articles:
    print(f"\n📝 最近处理的 {len(processed_articles)} 篇文章:\n")
    for idx, article in enumerate(processed_articles, 1):
        print(f"{idx}. {article.title[:60]}")
        print(f"   URL: {article.url}")
        print(f"   质量分数: {article.quality_score}")
        print(f"   主题: {article.topic or '未分类'}")
        print()
else:
    print("\n⚠️  还没有处理过的文章")

db.close()
