import bootstrap  # 初始化项目根路径，保证 test 目录脚本可直接运行
from app.database import SessionLocal
from app.models.source import Source

db = SessionLocal()

print("="*80)
print("📋 当前所有信息源")
print("="*80)

sources = db.query(Source).all()

if not sources:
    print("\n❌ 没有找到任何信息源")
else:
    for idx, source in enumerate(sources, 1):
        print(f"\n{idx}. ID: {source.id}")
        print(f"   名称: {source.name}")
        print(f"   类型: {source.source_type}")
        print(f"   URL: {source.url}")
        print(f"   激活: {'✅' if source.is_active else '❌'}")
        print(f"   主题: {source.topics}")
        print(f"   配置: {source.parser_config}")

print("\n" + "="*80)
print("💡 建议操作:")
print("="*80)

# 找出重复的源
name_count = {}
for source in sources:
    name_count[source.name] = name_count.get(source.name, 0) + 1

duplicates = [name for name, count in name_count.items() if count > 1]

if duplicates:
    print(f"\n⚠️  发现重复的信息源: {', '.join(duplicates)}")
    print("\n建议在 Swagger UI 中删除重复的源，只保留一个。")
    
    # 显示要删除的源
    for name in duplicates:
        dup_sources = [s for s in sources if s.name == name]
        print(f"\n  '{name}' 有 {len(dup_sources)} 个副本:")
        for s in dup_sources:
            print(f"    - ID {s.id}: {s.url}")
        print(f"    💡 建议保留 ID {dup_sources[0].id}，删除其他")

if any(s.source_type.value == 'dynamic' and '36kr' in s.url.lower() for s in sources):
    print("\n⚠️  36氪是动态网站，需要正确的 CSS 选择器")
    print("   当前可能使用了错误的选择器（如 Hacker News 的选择器）")
    print("   建议更新配置或暂时禁用，先用 Hacker News 测试")

db.close()
