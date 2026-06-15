import bootstrap  # 初始化项目根路径，保证 test 目录脚本可直接运行
# fix_sources.py
from app.database import SessionLocal
from app.models.source import Source

db = SessionLocal()

# 查看所有信息源
sources = db.query(Source).all()
print(f"共有 {len(sources)} 个信息源:\n")

for source in sources:
    print(f"ID: {source.id}")
    print(f"  Name: '{source.name}'")
    print(f"  Type: {source.source_type}")
    print(f"  URL: '{source.url}'")
    print(f"  Is Active: {source.is_active}")
    
    # 如果 URL 为空，提示用户
    if not source.url:
        print(f"  ⚠️  WARNING: URL is empty!")
    print()

# 询问是否删除有问题的源
empty_url_sources = [s for s in sources if not s.url]
if empty_url_sources:
    print(f"\n发现 {len(empty_url_sources)} 个 URL 为空的信息源")
    response = input("是否删除这些信息源？(y/n): ")
    if response.lower() == 'y':
        for source in empty_url_sources:
            db.delete(source)
        db.commit()
        print("已删除")

db.close()
