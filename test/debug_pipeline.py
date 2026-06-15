import bootstrap  # 初始化项目根路径，保证 test 目录脚本可直接运行
"""
IntelliBrief 数据调试诊断工具
============================
使用方法：
  python debug_pipeline.py              # 启动交互式菜单
  python debug_pipeline.py --auto 1     # 直接运行选项1（不进入菜单）
"""
import sys
import os
import json
import argparse

# 将项目根目录添加到系统路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models.article import Article, ArticleStatus
from app.models.source import Source
from utils.llm_router import llm_router


def print_separator(title: str):
    """打印带标题的分隔线，方便阅读"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


# ============================================================
# 功能1：查看爬虫爬取处理的数据
# ============================================================
def show_crawled_data():
    """查看爬虫爬取的文章数据（标题、正文、状态等）"""
    db = SessionLocal()
    try:
        print_separator("📰 爬虫数据一览")

        # 统计信息
        total = db.query(Article).count()
        pending = db.query(Article).filter(Article.status == ArticleStatus.pending).count()
        filtered = db.query(Article).filter(Article.status == ArticleStatus.filtered).count()
        processed = db.query(Article).filter(Article.status == ArticleStatus.processed).count()
        print(f"  总计: {total} 篇 | pending(待处理): {pending} | filtered(已过滤): {filtered} | processed(已处理): {processed}")

        if total == 0:
            print("\n  ⚠️  数据库中没有文章，请先运行爬虫")
            return

        # 列出最近的文章
        print()
        articles = db.query(Article).order_by(Article.fetched_at.desc()).limit(20).all()
        for idx, article in enumerate(articles, 1):
            print(f"\n  [{idx}] ID={article.id} | {article.title}")
            print(f"       URL: {article.url[:80]}")
            print(f"       状态: {article.status.value}", end="")
            if article.quality_score is not None:
                print(f" | 质量分: {article.quality_score}")
            else:
                print()
            print(f"       主题: {article.topic or '未分类'} | 标签: {article.tags or '无'}")
            print(f"       来源ID: {article.source_id} | 抓取时间: {article.fetched_at}")
            if article.content:
                print(f"       正文预览: {article.content[:120]}...")
    finally:
        db.close()


# ============================================================
# 功能2：清空爬虫爬取处理的数据
# ============================================================
def clear_crawled_data():
    """清空所有文章数据（谨慎操作！）"""
    db = SessionLocal()
    try:
        total = db.query(Article).count()
        if total == 0:
            print("\n  ⚠️  数据库中没有文章，无需清空")
            return

        print(f"\n  ⚠️  即将删除全部 {total} 篇文章数据！")
        confirm = input("  确认删除？(输入 yes 确认): ")
        if confirm.strip().lower() != "yes":
            print("  ❌ 已取消删除")
            return

        db.query(Article).delete()
        db.commit()
        print(f"  ✅ 已成功删除 {total} 篇文章数据")
    except Exception as e:
        db.rollback()
        print(f"  ❌ 删除失败: {e}")
    finally:
        db.close()


# ============================================================
# 功能3：查看调用大模型返回存入数据库的结果
# ============================================================
def show_llm_results():
    """查看大模型处理后的结果（摘要、评分、分类等）"""
    db = SessionLocal()
    try:
        print_separator("🤖 大模型处理结果一览")

        # 筛选出经过 LLM 处理过的文章（processed 状态且有摘要）
        articles = (
            db.query(Article)
            .filter(Article.status == ArticleStatus.processed)
            .filter(Article.summary.isnot(None))
            .order_by(Article.fetched_at.desc())
            .all()
        )

        if not articles:
            # 退而求其次：显示所有有质量分数的文章
            articles = (
                db.query(Article)
                .filter(Article.quality_score.isnot(None))
                .order_by(Article.fetched_at.desc())
                .all()
            )

        if not articles:
            print("\n  ⚠️  还没有大模型处理过的数据")
            print("  提示: 先运行完整流水线（POST /tasks/run-all），等待 AI 处理完成")
            return

        print(f"\n  共 {len(articles)} 篇文章经过了大模型处理\n")

        for idx, article in enumerate(articles, 1):
            print(f"  [{idx}] ID={article.id} | {article.title}")
            print(f"       URL: {article.url[:60]}")
            print(f"       状态: {article.status.value}")

            # 显示质量评分
            if article.quality_score is not None:
                print(f"       质量评分: {article.quality_score}/100")

            # 显示主题和标签（LLM 分类结果）
            if article.topic:
                print(f"       主题分类: {article.topic}")
            if article.tags:
                print(f"       标签: {article.tags}")

            # 显示摘要（LLM 生成结果）
            if article.summary:
                try:
                    summary_data = json.loads(article.summary)
                    print(f"       一句话总结: {summary_data.get('one_liner', '')[:100]}")
                    key_points = summary_data.get('key_points', [])
                    for kp in key_points[:5]:
                        print(f"       📌 {kp[:80]}")
                except json.JSONDecodeError:
                    print(f"       摘要(原始): {article.summary[:150]}")
            print()
    finally:
        db.close()


# ============================================================
# 功能4：清空调用大模型返回存入数据库的结果
# ============================================================
def clear_llm_results():
    """清空大模型处理结果（保留文章，仅重置 AI 相关字段）"""
    db = SessionLocal()
    try:
        # 统计有多少文章有大模型处理结果
        processed_count = db.query(Article).filter(Article.status == ArticleStatus.processed).count()
        filtered_count = db.query(Article).filter(Article.status == ArticleStatus.filtered).count()
        has_summary = db.query(Article).filter(Article.summary.isnot(None)).count()
        total_affected = processed_count + filtered_count + has_summary

        if total_affected == 0:
            print("\n  ⚠️  没有大模型处理过的数据需要清空")
            return

        print(f"\n  ⚠️  即将重置以下数据：")
        print(f"      - processed 状态文章: {processed_count} 篇 → 重置为 pending")
        print(f"      - filtered 状态文章: {filtered_count} 篇 → 重置为 pending")
        print(f"      - 已有摘要的文章: {has_summary} 篇 → 清空摘要")
        print(f"      - 同时清空: 质量评分、主题分类、标签")

        confirm = input("  确认重置？(输入 yes 确认): ")
        if confirm.strip().lower() != "yes":
            print("  ❌ 已取消重置")
            return

        # 重置所有文章状态为 pending
        updated = (
            db.query(Article)
            .filter(Article.status.in_([ArticleStatus.processed, ArticleStatus.filtered]))
            .update({Article.status: ArticleStatus.pending}, synchronize_session=False)
        )

        # 清空 LLM 相关字段
        db.query(Article).update(
            {
                Article.summary: None,
                Article.tags: None,
                Article.topic: None,
                Article.quality_score: None,
            },
            synchronize_session=False,
        )

        db.commit()
        print(f"  ✅ 已重置 {total_affected} 篇文章的 LLM 处理结果，所有文章状态恢复为 pending")
        print("  提示: 可以重新运行流水线进行 AI 处理")
    except Exception as e:
        db.rollback()
        print(f"  ❌ 重置失败: {e}")
    finally:
        db.close()


# ============================================================
# 功能6：查看数据库中的源
# ============================================================
def show_sources():
    """查看所有信息源配置"""
    db = SessionLocal()
    try:
        print_separator("📡 信息源一览")
        sources = db.query(Source).order_by(Source.id).all()
        if not sources:
            print("\n  ⚠️  数据库中没有配置任何信息源")
            print("  提示: 通过 POST /sources/ API 添加信息源")
            return

        print(f"\n  共 {len(sources)} 个信息源\n")
        for src in sources:
            print(f"  🆔 {src.id} | {src.name}")
            print(f"     URL: {src.url}")
            type_name = src.source_type.value if hasattr(src.source_type, 'value') else src.source_type
            print(f"     类型: {type_name} | 激活: {'✅' if src.is_active else '❌'}")
            if src.topics:
                print(f"     关注主题: {src.topics}")
            if src.parser_config:
                print(f"     爬取配置: {json.dumps(src.parser_config, ensure_ascii=False)}")
            # 统计该源的文章数
            article_count = db.query(Article).filter(Article.source_id == src.id).count()
            print(f"     已爬取文章: {article_count} 篇")
            print()
    finally:
        db.close()


# ============================================================
# 功能7：清空数据库中的源
# ============================================================
def clear_sources():
    """清空所有信息源（谨慎操作！同时会清空关联的文章）"""
    db = SessionLocal()
    try:
        total_sources = db.query(Source).count()
        total_articles = db.query(Article).count()

        if total_sources == 0:
            print("\n  ⚠️  数据库中没有信息源，无需清空")
            return

        print(f"\n  ⚠️  即将删除全部 {total_sources} 个信息源和关联的 {total_articles} 篇文章！")
        print(f"      此操作不可撤销！")
        confirm = input("  确认删除？(输入 yes 确认): ")
        if confirm.strip().lower() != "yes":
            print("  ❌ 已取消删除")
            return

        # 先删除关联的文章，再删除信息源
        db.query(Article).delete()
        db.query(Source).delete()
        db.commit()
        print(f"  ✅ 已成功删除 {total_sources} 个信息源和 {total_articles} 篇文章")
        print("  提示: 通过 POST /sources/ API 重新添加信息源")
    except Exception as e:
        db.rollback()
        print(f"  ❌ 删除失败: {e}")
    finally:
        db.close()


# ============================================================
# 功能5：测试大模型是否可用
# ============================================================
def test_llm_available():
    """测试智谱和 DeepSeek 大模型 API 是否正常"""
    print_separator("🤖 大模型可用性测试")

    # 测试智谱 GLM
    print("\n  [测试 1] 智谱 GLM-4-Flash...")
    try:
        messages = [
            {"role": "user", "content": "请用一句话说明什么是大语言模型，返回 JSON。"}
        ]
        result = llm_router.call_llm(
            provider='zhipu',
            messages=messages,
            response_format={"type": "json_object"}
        )
        print(f"  ✅ 智谱调用成功！")
        print(f"  返回内容: {result}")
    except Exception as e:
        print(f"  ❌ 智谱调用失败: {e}")
        print(f"     可能原因: API Key 无效、网络不通、QPS 超限")

    # 测试 DeepSeek
    print("\n  [测试 2] DeepSeek...")
    try:
        messages = [
            {"role": "user", "content": "请用一句话总结 AI 技术的主要发展趋势。"}
        ]
        result = llm_router.call_llm(
            provider='deepseek',
            messages=messages
        )
        print(f"  ✅ DeepSeek 调用成功！")
        print(f"  返回内容: {result}")
    except Exception as e:
        print(f"  ❌ DeepSeek 调用失败: {e}")
        print(f"     可能原因: API Key 无效、网络不通、QPS 超限")


# ============================================================
# 菜单与主流程
# ============================================================
def show_menu():
    """打印交互式菜单"""
    print("\n" + "=" * 60)
    print("   IntelliBrief 数据调试诊断工具")
    print("=" * 60)
    print("  1. 📰 查看爬虫爬取处理的数据")
    print("  2. 🗑️  清空爬虫爬取处理的数据")
    print("  3. 🤖 查看调用大模型返回存入数据库的结果")
    print("  4. 🔄 清空调用大模型返回存入数据库的结果")
    print("  5. 🧪 测试大模型是否可用")
    print("  6. 📡 查看数据库中的源")
    print("  7. 🗑️  清空数据库中的源")
    print("  0. 🚪 退出")
    print("=" * 60)


# 功能选项映射表
OPTIONS = {
    "1": ("查看爬虫爬取处理的数据", show_crawled_data),
    "2": ("清空爬虫爬取处理的数据", clear_crawled_data),
    "3": ("查看调用大模型返回存入数据库的结果", show_llm_results),
    "4": ("清空调用大模型返回存入数据库的结果", clear_llm_results),
    "5": ("测试大模型是否可用", test_llm_available),
    "6": ("查看数据库中的源", show_sources),
    "7": ("清空数据库中的源", clear_sources),
}


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="IntelliBrief 数据调试诊断工具")
    parser.add_argument(
        "--auto", type=str, metavar="选项编号",
        help="直接运行指定选项（1-7），不进入交互式菜单"
    )
    args = parser.parse_args()

    # 如果指定了 --auto 参数，直接运行对应功能
    if args.auto:
        option = OPTIONS.get(args.auto)
        if option:
            print(f"\n  ▶ 正在执行: {option[0]}")
            option[1]()
            print("\n" + "=" * 60)
            print("  ✅ 操作完成")
            print("=" * 60)
        else:
            print(f"\n  ❌ 无效选项: {args.auto}，可用选项: 1-7")
        return

    # 交互式菜单循环
    while True:
        show_menu()
        choice = input("\n  请输入选项 [0-7]: ").strip()

        if choice == "0":
            print("\n  👋 再见！")
            break

        option = OPTIONS.get(choice)
        if option:
            option[1]()
            input("\n  按回车键继续...")
        else:
            print("\n  ❌ 无效选项，请输入 0-7 之间的数字")


if __name__ == "__main__":
    main()
