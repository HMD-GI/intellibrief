import argparse  # 导入命令行参数模块，用于解析用户传入的自动执行选项。
import sys  # 导入系统模块，用于脚本退出时返回状态码。

import bootstrap  # 导入测试目录引导模块，确保脚本从 test 目录直接运行时也能找到项目根路径。
from app.database import SessionLocal  # 导入数据库会话工厂，用于创建独立的数据库连接会话。
from app.models.article import Article, ArticleStatus  # 导入文章模型和文章状态枚举，用于查看与清理爬虫文章数据。
from app.models.brief import Brief  # 导入简报模型，用于查看与清理生成后的简报结果。
from app.models.brief_run import ArticleRun, BriefRun  # 导入运行隔离表模型，用于查看与清理 AI 处理过程结果。
from app.models.source import Source  # 导入数据源模型，用于查看与清理数据库中的爬虫源配置。
from utils.llm_router import llm_router  # 导入统一大模型路由器，用于测试 first/second/third 三个模型槽位是否可用。


MENU_TITLE = "IntelliBrief 数据调试控制台"  # 定义统一菜单标题，方便交互式菜单顶部复用。
PREVIEW_LENGTH = 120  # 定义正文与摘要预览长度，避免终端输出过长影响阅读。
LIST_LIMIT = 20  # 定义列表类查询默认显示条数，避免一次打印过多记录。
CONFIRM_TEXT = "yes"  # 定义危险操作确认口令，防止误删数据库数据。


def print_separator(title: str) -> None:  # 定义分隔线打印函数，title 表示当前功能标题。
    print("\n" + "=" * 72)  # 打印上边框，增强终端输出可读性。
    print(f"  {title}")  # 打印当前功能标题，便于用户识别所在功能。
    print("=" * 72)  # 打印下边框，形成完整的视觉分隔。


def _preview_text(value: str | None, limit: int = PREVIEW_LENGTH) -> str:  # 定义文本预览函数，value 是原始文本，limit 是保留长度。
    if not value:  # 如果文本为空，则直接返回占位符。
        return "-"  # 返回短横线，表示当前字段暂无数据。
    text = " ".join(str(value).split())  # 将多余换行与空白折叠成单空格，便于终端单行展示。
    return text[:limit] + ("..." if len(text) > limit else "")  # 超长时追加省略号，否则原样返回。


def _open_db():  # 定义数据库会话创建函数，统一所有功能入口的连接方式。
    return SessionLocal()  # 返回一个独立数据库会话，调用方负责关闭。


def show_crawled_data() -> None:  # 定义功能1：查看爬虫抓取处理的数据。
    db = _open_db()  # 创建数据库会话，用于查询 articles 表与关联信息。
    try:  # 使用 try/finally 保证数据库连接最终会被关闭。
        print_separator("1. 查看爬虫爬取处理的数据")  # 打印当前功能标题。

        total_articles = db.query(Article).count()  # 统计文章总数，反映当前已抓取数据规模。
        pending_articles = db.query(Article).filter(Article.status == ArticleStatus.pending).count()  # 统计待处理文章数量。
        filtered_articles = db.query(Article).filter(Article.status == ArticleStatus.filtered).count()  # 统计被过滤文章数量。
        processed_articles = db.query(Article).filter(Article.status == ArticleStatus.processed).count()  # 统计已处理文章数量。
        total_article_runs = db.query(ArticleRun).count()  # 统计文章运行结果数量，反映 AI 隔离表写入情况。

        print(f"文章总数：{total_articles}")  # 输出文章总数。
        print(f"待处理文章：{pending_articles}")  # 输出待处理文章数量。
        print(f"已过滤文章：{filtered_articles}")  # 输出被过滤文章数量。
        print(f"已处理文章：{processed_articles}")  # 输出已处理文章数量。
        print(f"AI 运行结果条数：{total_article_runs}")  # 输出 AI 运行结果数量。

        if total_articles == 0:  # 如果数据库里没有文章，则不再继续打印明细。
            print("当前数据库中没有抓取到任何文章数据。")  # 提示用户当前没有可查看的爬虫数据。
            return  # 提前结束函数。

        latest_articles = (  # 定义最近文章查询，用于展示最新抓取数据。
            db.query(Article)  # 从文章表开始查询。
            .order_by(Article.fetched_at.desc(), Article.id.desc())  # 按抓取时间与主键倒序，保证最新记录排在前面。
            .limit(LIST_LIMIT)  # 限制最多显示 LIST_LIMIT 条。
            .all()  # 执行查询并返回结果列表。
        )

        print("\n最近抓取文章：")  # 输出分节标题，开始展示文章明细。
        for index, article in enumerate(latest_articles, start=1):  # 遍历最近文章，index 为显示序号，article 为文章对象。
            source_name = article.source.name if article.source else "-"  # 提取来源名称，若无来源则显示占位符。
            print(f"[{index}] ID={article.id} | 状态={article.status.value} | 来源={source_name}")  # 输出文章基础标识信息。
            print(f"     标题：{_preview_text(article.title, 80)}")  # 输出文章标题预览。
            print(f"     URL：{article.url}")  # 输出文章原始链接，便于人工复查来源页面。
            print(f"     文章日期：{article.article_date or '-'} | 抓取时间：{article.fetched_at or '-'}")  # 输出发布日期与抓取时间。
            print(f"     正文预览：{_preview_text(article.content)}")  # 输出正文预览，便于判断抓取清洗是否成功。
            print()  # 每篇文章后留空行，提升终端可读性。
    finally:  # finally 块负责统一释放数据库资源。
        db.close()  # 关闭数据库会话，避免连接泄漏。


def clear_crawled_data() -> None:  # 定义功能2：清空爬虫抓取处理的数据。
    db = _open_db()  # 创建数据库会话，用于执行删除操作。
    try:  # 使用事务保护删除流程。
        article_count = db.query(Article).count()  # 统计文章数量，用于删除前提示。
        article_run_count = db.query(ArticleRun).count()  # 统计文章运行结果数量，用于删除前提示。
        brief_run_count = db.query(BriefRun).count()  # 统计简报运行记录数量，用于删除前提示。
        brief_count = db.query(Brief).count()  # 统计简报数量，用于删除前提示。

        if article_count == 0 and article_run_count == 0 and brief_run_count == 0 and brief_count == 0:  # 如果没有任何相关数据，则无需执行删除。
            print("当前数据库中没有需要清空的抓取与处理数据。")  # 提示无需执行危险操作。
            return  # 直接返回。

        print_separator("2. 清空爬虫爬取处理的数据")  # 打印当前功能标题。
        print(f"将删除文章：{article_count} 条")  # 提示将删除的文章数量。
        print(f"将删除文章运行结果：{article_run_count} 条")  # 提示将删除的文章运行结果数量。
        print(f"将删除简报运行记录：{brief_run_count} 条")  # 提示将删除的简报运行记录数量。
        print(f"将删除简报：{brief_count} 条")  # 提示将删除的简报数量。

        confirm = input(f"确认删除以上数据请输入 {CONFIRM_TEXT}：").strip().lower()  # 读取用户确认口令，避免误删。
        if confirm != CONFIRM_TEXT:  # 如果确认口令不匹配，则取消删除。
            print("已取消清空操作。")  # 提示用户本次没有执行删除。
            return  # 提前返回。

        db.query(Brief).delete()  # 先删除简报结果表，避免后续运行记录被外键引用。
        db.query(ArticleRun).delete()  # 删除文章运行结果表，清空 AI 处理隔离数据。
        db.query(BriefRun).delete()  # 删除简报运行记录表，清空多次运行的流程痕迹。
        db.query(Article).delete()  # 最后删除文章表，完成抓取数据清空。
        db.commit()  # 提交事务，使删除正式落库。
        print("爬虫抓取与处理数据已清空。")  # 输出清理完成提示。
    except Exception as exc:  # 捕获删除过程中的异常，便于回滚。
        db.rollback()  # 回滚事务，防止部分删除导致数据不一致。
        print(f"清空失败：{exc}")  # 输出错误信息，方便进一步排查。
    finally:  # finally 中统一关闭数据库会话。
        db.close()  # 释放数据库连接。


def show_llm_results() -> None:  # 定义功能3：查看调用大模型返回存入数据库的结果。
    db = _open_db()  # 创建数据库会话，用于查询 brief_runs、article_runs 与 briefs 表。
    try:  # 使用 try/finally 保证查询后会话能关闭。
        print_separator("3. 查看调用大模型返回存入数据库的结果")  # 打印当前功能标题。

        total_brief_runs = db.query(BriefRun).count()  # 统计简报运行记录总数，反映总体生成次数。
        total_article_runs = db.query(ArticleRun).count()  # 统计文章运行结果总数，反映 AI 逐篇处理条数。
        total_briefs = db.query(Brief).count()  # 统计生成的简报条数。

        print(f"简报运行记录：{total_brief_runs}")  # 输出简报运行记录数量。
        print(f"文章运行结果：{total_article_runs}")  # 输出文章运行结果数量。
        print(f"已生成简报：{total_briefs}")  # 输出简报数量。

        latest_runs = (  # 定义最近运行查询，用于展示最新 AI 处理结果。
            db.query(BriefRun)  # 从简报运行表开始查询。
            .order_by(BriefRun.created_at.desc(), BriefRun.id.desc())  # 按创建时间倒序排列。
            .limit(10)  # 最多只看最近 10 次运行。
            .all()  # 执行查询并返回结果列表。
        )

        if not latest_runs:  # 如果没有任何运行记录，则提示用户尚未执行 AI 流程。
            print("当前数据库中没有大模型处理结果。")  # 输出空结果提示。
            return  # 结束函数。

        print("\n最近简报运行：")  # 输出分节标题。
        for run in latest_runs:  # 遍历最近运行记录。
            article_run_count = db.query(ArticleRun).filter(ArticleRun.brief_run_id == run.id).count()  # 统计当前运行下的文章运行结果数量。
            brief_count = db.query(Brief).filter(Brief.brief_run_id == run.id).count()  # 统计当前运行下的简报数量。
            print(f"运行ID={run.id} | 主题={run.topic} | 状态={run.status.value}")  # 输出运行基础信息。
            print(f"     run_key：{run.run_key}")  # 输出运行唯一键，便于定位隔离批次。
            print(f"     关键词：{run.keywords or []}")  # 输出本次运行使用的关键词列表。
            print(f"     文章结果数：{article_run_count} | 简报数：{brief_count}")  # 输出当前运行的结果规模。
            print(f"     创建时间：{run.created_at} | 更新时间：{run.updated_at}")  # 输出运行时间信息。
            if run.error_message:  # 如果本次运行失败或记录了错误，则额外显示错误详情。
                print(f"     错误信息：{_preview_text(run.error_message)}")  # 输出错误信息预览。
            print()  # 每条运行后空一行。

        latest_article_runs = (  # 定义最近文章运行结果查询，用于查看逐篇 AI 摘要、打分和分类。
            db.query(ArticleRun)  # 从文章运行结果表开始查询。
            .order_by(ArticleRun.updated_at.desc(), ArticleRun.id.desc())  # 按更新时间倒序，优先看最新结果。
            .limit(LIST_LIMIT)  # 限制打印条数，避免输出过长。
            .all()  # 执行查询。
        )

        print("最近文章 AI 结果：")  # 输出分节标题。
        for index, row in enumerate(latest_article_runs, start=1):  # 遍历每条文章运行结果。
            article_title = row.article.title if row.article else "-"  # 获取关联文章标题，若不存在则显示占位符。
            print(f"[{index}] 运行ID={row.brief_run_id} | 文章ID={row.article_id} | 状态={row.status.value}")  # 输出结果行基础信息。
            print(f"     标题：{_preview_text(article_title, 80)}")  # 输出文章标题预览。
            print(f"     分数：{row.score if row.score is not None else '-'} | 分类：{row.classified_topic or '-'}")  # 输出打分与分类结果。
            print(f"     标签：{row.tags or '-'}")  # 输出标签字段。
            print(f"     摘要：{_preview_text(row.summary)}")  # 输出摘要内容预览。
            print()  # 每条结果后空一行。
    finally:  # finally 负责关闭数据库会话。
        db.close()  # 释放数据库连接。


def clear_llm_results() -> None:  # 定义功能4：清空调用大模型返回存入数据库的结果。
    db = _open_db()  # 创建数据库会话，用于删除 AI 运行结果并重置 legacy 字段。
    try:  # 使用 try/except/finally 包裹事务。
        article_run_count = db.query(ArticleRun).count()  # 统计文章运行结果数量，用于提示影响范围。
        brief_run_count = db.query(BriefRun).count()  # 统计简报运行记录数量，用于提示影响范围。
        brief_count = db.query(Brief).count()  # 统计简报数量，用于提示影响范围。
        article_count = db.query(Article).count()  # 统计文章数量，用于提示需要重置多少篇文章的 legacy 字段。

        if article_run_count == 0 and brief_run_count == 0 and brief_count == 0 and article_count == 0:  # 如果数据库几乎为空，则无需执行清理。
            print("当前数据库中没有需要清空的大模型结果。")  # 输出无需操作提示。
            return  # 结束函数。

        print_separator("4. 清空调用大模型返回存入数据库的结果")  # 打印当前功能标题。
        print(f"将删除文章运行结果：{article_run_count} 条")  # 提示将删除的文章运行结果数量。
        print(f"将删除简报运行记录：{brief_run_count} 条")  # 提示将删除的简报运行记录数量。
        print(f"将删除简报：{brief_count} 条")  # 提示将删除的简报数量。
        print(f"将重置文章 legacy AI 字段：{article_count} 条")  # 提示将重置 legacy AI 字段的文章数量。

        confirm = input(f"确认删除以上 AI 结果请输入 {CONFIRM_TEXT}：").strip().lower()  # 获取用户确认口令。
        if confirm != CONFIRM_TEXT:  # 如果用户未输入正确口令，则取消操作。
            print("已取消清空操作。")  # 输出取消提示。
            return  # 提前结束函数。

        db.query(Brief).delete()  # 删除简报表，清空已生成的 HTML 简报结果。
        db.query(ArticleRun).delete()  # 删除文章运行结果表，清空 AI 对单篇文章的处理记录。
        db.query(BriefRun).delete()  # 删除简报运行记录表，清空批次运行历史。
        db.query(Article).update(  # 批量重置 articles 表中的兼容字段，保证重新跑流程时状态干净。
            {
                Article.summary: None,  # 清空旧版兼容摘要字段。
                Article.tags: None,  # 清空旧版兼容标签字段。
                Article.topic: None,  # 清空旧版兼容主题字段。
                Article.quality_score: None,  # 清空旧版兼容质量分数字段。
                Article.status: ArticleStatus.pending,  # 将文章状态统一重置为 pending，便于重新执行 AI 流程。
            },
            synchronize_session=False,  # 关闭会话同步以提升批量更新效率。
        )
        db.commit()  # 提交事务，正式生效所有删除与重置操作。
        print("大模型结果已清空，文章状态已重置为 pending。")  # 输出清理完成提示。
    except Exception as exc:  # 捕获异常，避免部分操作已执行但事务未提交。
        db.rollback()  # 回滚事务，保持数据库一致性。
        print(f"清空失败：{exc}")  # 输出失败原因。
    finally:  # finally 块统一关闭会话。
        db.close()  # 释放数据库连接。


def test_llm_available() -> None:  # 定义功能5：测试大模型是否可用。
    print_separator("5. 测试大模型是否可用")  # 打印当前功能标题。
    providers = ["first", "second", "third"]  # 定义三个统一模型槽位名称，和当前项目配置保持一致。
    for provider in providers:  # 依次测试每个模型槽位。
        print(f"正在测试模型槽位：{provider}")  # 输出当前正在测试的槽位名称。
        try:  # 对单个槽位调用进行异常保护。
            messages = [  # 定义最小测试消息列表，只用一轮用户消息判断接口是否可用。
                {"role": "user", "content": "请用一句中文短句回复：模型连通正常。"}  # 构造简单提示词，减少模型响应时间与成本。
            ]
            result = llm_router.call_llm(provider=provider, messages=messages, max_retries=1)  # 调用统一路由器测试当前槽位。
            print(f"测试成功：{_preview_text(result, 80)}")  # 输出模型返回内容预览。
        except Exception as exc:  # 捕获调用失败异常，避免一个槽位失败影响全部测试。
            print(f"测试失败：{exc}")  # 输出失败信息，便于检查 key、模型名或 base_url。
        print()  # 每个槽位测试后空一行，增强输出可读性。


def show_sources() -> None:  # 定义功能6：查看数据库中的源。
    db = _open_db()  # 创建数据库会话，用于查询 sources 表。
    try:  # 使用 try/finally 保证查询结束后会话关闭。
        print_separator("6. 查看数据库中的源")  # 打印当前功能标题。
        sources = db.query(Source).order_by(Source.id.asc()).all()  # 查询所有数据源并按主键升序输出。

        if not sources:  # 如果没有任何数据源，则给出明确提示。
            print("当前数据库中没有配置任何数据源。")  # 提示用户当前源表为空。
            return  # 提前结束函数。

        print(f"数据源总数：{len(sources)}\n")  # 输出源数量统计。
        for source in sources:  # 遍历每个数据源对象。
            article_count = db.query(Article).filter(Article.source_id == source.id).count()  # 统计该源当前关联的文章数量。
            source_type = source.source_type.value if hasattr(source.source_type, "value") else str(source.source_type)  # 兼容枚举和值两种显示方式。
            print(f"ID={source.id} | 名称={source.name}")  # 输出源主键与名称。
            print(f"     类型：{source_type} | 启用：{'是' if source.is_active else '否'}")  # 输出源类型和启用状态。
            print(f"     URL：{source.url}")  # 输出源地址，便于人工复查是否有效。
            print(f"     主题：{source.topics or '-'}")  # 输出源主题配置。
            print(f"     解析配置：{source.parser_config or {}}")  # 输出解析配置字典，便于检查 XPath/CSS 选择器。
            print(f"     已抓取文章数：{article_count}")  # 输出当前源对应的文章数量。
            print()  # 每个源后空一行。
    finally:  # finally 中统一关闭数据库会话。
        db.close()  # 释放数据库连接。


def clear_sources() -> None:  # 定义功能7：清空数据库中的源。
    db = _open_db()  # 创建数据库会话，用于执行全量删除。
    try:  # 使用事务保护整个删除过程。
        source_count = db.query(Source).count()  # 统计源数量，用于删除前提示。
        article_count = db.query(Article).count()  # 统计文章数量，用于删除前提示。
        article_run_count = db.query(ArticleRun).count()  # 统计文章运行结果数量，用于删除前提示。
        brief_run_count = db.query(BriefRun).count()  # 统计简报运行记录数量，用于删除前提示。
        brief_count = db.query(Brief).count()  # 统计简报数量，用于删除前提示。

        if source_count == 0:  # 如果没有源，则无需执行删除。
            print("当前数据库中没有数据源，无需清空。")  # 输出无需删除提示。
            return  # 提前结束函数。

        print_separator("7. 清空数据库中的源")  # 打印当前功能标题。
        print(f"将删除数据源：{source_count} 条")  # 提示将删除的源数量。
        print(f"将删除文章：{article_count} 条")  # 提示将删除的文章数量。
        print(f"将删除文章运行结果：{article_run_count} 条")  # 提示将删除的文章运行结果数量。
        print(f"将删除简报运行记录：{brief_run_count} 条")  # 提示将删除的简报运行记录数量。
        print(f"将删除简报：{brief_count} 条")  # 提示将删除的简报数量。

        confirm = input(f"确认删除全部数据源及关联数据请输入 {CONFIRM_TEXT}：").strip().lower()  # 获取用户确认输入。
        if confirm != CONFIRM_TEXT:  # 如果用户没有明确确认，则取消危险操作。
            print("已取消清空操作。")  # 输出取消提示。
            return  # 直接返回。

        db.query(Brief).delete()  # 先删除简报结果，避免保留孤立简报数据。
        db.query(ArticleRun).delete()  # 删除文章运行结果表，避免保留孤立运行结果。
        db.query(BriefRun).delete()  # 删除简报运行记录表，清理批次隔离数据。
        db.query(Article).delete()  # 删除所有文章记录，清理源关联抓取数据。
        db.query(Source).delete()  # 最后删除源表，实现完整重置。
        db.commit()  # 提交事务，正式生效所有删除。
        print("数据库中的数据源及关联数据已清空。")  # 输出操作成功提示。
    except Exception as exc:  # 捕获删除过程中的异常。
        db.rollback()  # 回滚事务，避免部分表已删、部分表未删。
        print(f"清空失败：{exc}")  # 输出失败原因。
    finally:  # finally 中统一释放数据库连接。
        db.close()  # 关闭数据库会话。


def show_menu() -> None:  # 定义菜单打印函数，用于交互式显示全部可选功能。
    print("\n" + "=" * 72)  # 打印菜单上边框。
    print(f"  {MENU_TITLE}")  # 打印菜单标题。
    print("=" * 72)  # 打印菜单下边框。
    print("  1. 📰 查看爬虫爬取处理的数据")  # 输出功能1说明。
    print("  2. 🗑️  清空爬虫爬取处理的数据")  # 输出功能2说明。
    print("  3. 🤖 查看调用大模型返回存入数据库的结果")  # 输出功能3说明。
    print("  4. 🔄 清空调用大模型返回存入数据库的结果")  # 输出功能4说明。
    print("  5. 🧪 测试大模型是否可用")  # 输出功能5说明。
    print("  6. 📡 查看数据库中的源")  # 输出功能6说明。
    print("  7. 🗑️  清空数据库中的源")  # 输出功能7说明。
    print("  0. 🚪 退出")  # 输出退出选项说明。
    print("=" * 72)  # 打印菜单底部边框。


OPTIONS = {  # 定义菜单选项映射表，键为功能编号，值为功能名称和处理函数。
    "1": ("查看爬虫爬取处理的数据", show_crawled_data),  # 将编号1映射到查看爬虫数据函数。
    "2": ("清空爬虫爬取处理的数据", clear_crawled_data),  # 将编号2映射到清空爬虫数据函数。
    "3": ("查看调用大模型返回存入数据库的结果", show_llm_results),  # 将编号3映射到查看 AI 结果函数。
    "4": ("清空调用大模型返回存入数据库的结果", clear_llm_results),  # 将编号4映射到清空 AI 结果函数。
    "5": ("测试大模型是否可用", test_llm_available),  # 将编号5映射到测试模型函数。
    "6": ("查看数据库中的源", show_sources),  # 将编号6映射到查看源函数。
    "7": ("清空数据库中的源", clear_sources),  # 将编号7映射到清空源函数。
}  # 结束菜单映射表定义。


def run_single_option(option_key: str) -> int:  # 定义单选项执行函数，option_key 表示用户传入的编号。
    option = OPTIONS.get(option_key)  # 从映射表里读取对应功能配置。
    if not option:  # 如果编号不存在，则返回失败状态码。
        print(f"无效选项：{option_key}，可用选项为 0-7。")  # 输出无效选项提示。
        return 1  # 返回非零状态码，表示参数错误。
    print_separator(f"执行功能：{option[0]}")  # 打印当前执行功能名称。
    option[1]()  # 调用对应函数执行功能。
    return 0  # 返回零状态码，表示执行完成。


def main() -> int:  # 定义主函数，统一处理自动模式和交互模式。
    parser = argparse.ArgumentParser(description=MENU_TITLE)  # 创建命令行参数解析器，描述文本使用统一标题。
    parser.add_argument("--auto", type=str, help="直接执行指定编号功能，例如 --auto 6。")  # 定义自动执行参数，便于脚本化调用。
    args = parser.parse_args()  # 解析命令行参数，得到用户传入的功能编号。

    if args.auto:  # 如果用户提供了自动执行编号，则直接执行对应功能。
        return run_single_option(args.auto)  # 返回对应功能执行状态码。

    while True:  # 开始交互式菜单循环，直到用户选择退出。
        show_menu()  # 打印菜单，让用户看到可用功能。
        choice = input("请输入选项编号 [0-7]：").strip()  # 读取用户输入并去除首尾空格。

        if choice == "0":  # 如果用户输入0，则退出程序。
            print("已退出调试控制台。")  # 输出退出提示。
            return 0  # 返回零状态码，表示正常退出。

        result_code = run_single_option(choice)  # 执行当前选择的功能，并接收状态码。
        if result_code == 0:  # 如果功能执行成功，则等待用户确认后再继续显示菜单。
            input("\n按回车键返回主菜单...")  # 阻塞等待，方便用户阅读本次输出结果。


if __name__ == "__main__":  # 仅在直接运行本脚本时进入主函数。
    sys.exit(main())  # 使用主函数返回值作为进程退出码，方便自动化脚本判断结果。
