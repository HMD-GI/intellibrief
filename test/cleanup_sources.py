import bootstrap  # 初始化项目根路径，保证 test 目录脚本可直接运行
from app.database import SessionLocal
from app.models.source import Source

db = SessionLocal()

print("="*80)
print("🗑️  清理重复的信息源")
print("="*80)

# 查找所有 36氪 相关的源
kr_sources = db.query(Source).filter(Source.name.like("%36氪%")).all()

if not kr_sources:
    print("\n✅ 没有找到 36氪 相关的信息源")
else:
    print(f"\n找到 {len(kr_sources)} 个 36氪 相关的信息源:\n")
    for source in kr_sources:
        print(f"  ID {source.id}: {source.name}")
        print(f"    URL: {source.url}")
        print(f"    配置: {source.parser_config}")
        print()
    
    response = input("是否删除所有这些源？(y/n): ")
    if response.lower() == 'y':
        for source in kr_sources:
            db.delete(source)
        db.commit()
        print(f"\n✅ 已删除 {len(kr_sources)} 个信息源")
    else:
        print("\n❌ 取消操作")

db.close()
