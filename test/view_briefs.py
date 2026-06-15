import bootstrap  # 初始化项目根路径，保证 test 目录脚本可直接运行
from app.database import SessionLocal
from app.models.brief import Brief
from datetime import date

db = SessionLocal()

# 查看所有简报
briefs = db.query(Brief).order_by(Brief.date.desc()).all()

if not briefs:
    print("❌ 还没有生成任何简报")
else:
    print(f"📊 共有 {len(briefs)} 份简报:\n")
    for brief in briefs:
        print(f"📅 日期: {brief.date}")
        print(f"📝 标题: {brief.title}")
        print(f"🔗 文章数量: {len(brief.article_ids)}")
        print(f"🌐 访问链接: http://localhost:8000/briefs/{brief.date.isoformat()}")
        print("-" * 80)
        print()

# 查看今天的简报（如果存在）
today = date.today()
today_brief = db.query(Brief).filter(Brief.date == today).first()

if today_brief:
    print("\n✅ 今天的简报已生成！")
    print(f"📄 HTML 长度: {len(today_brief.html_content)} 字符")
    
    # 保存为 HTML 文件
    filename = f"brief_{today.isoformat()}.html"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(today_brief.html_content)
    print(f"💾 已保存到文件: {filename}")
    print(f"🌐 在线查看: http://localhost:8000/briefs/{today.isoformat()}")
else:
    print("\n⚠️  今天还没有生成简报")

db.close()
