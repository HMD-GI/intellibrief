import bootstrap  # 初始化项目根路径，保证 test 目录脚本可直接运行
import os
import re
from app.database import SessionLocal
from app.models.source import Source
from crawlers import get_crawler
from processor.cleaner import extract_clean_content

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

def _safe_filename(text: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", text or "")
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._ ")
    return cleaned or "article"

def main():
    db = SessionLocal()
    try:
        source = db.query(Source).filter(Source.name == "环球网-国际新闻").first()
        if not source:
            print("❌ 未找到源：环球网-国际新闻")
            return

        crawler = get_crawler(source)
        articles = crawler.fetch()[:5]
        print(f"抓到 {len(articles)} 篇候选文章\n")
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        for idx, item in enumerate(articles, 1):
            content = extract_clean_content(item.raw_html or "", item.url or "")
            preview = content[:300].replace("\n", " ").strip()
            file_name = f"{idx:02d}_{_safe_filename(item.title)}.txt"
            file_path = os.path.join(OUTPUT_DIR, file_name)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            print(f"[{idx}] {item.title}")
            print(f"    url: {item.url}")
            print(f"    date: {item.article_date}")
            print(f"    raw_html_len: {len(item.raw_html or '')}")
            print(f"    clean_len: {len(content)}")
            print(f"    article_preview: {preview}")
            if not content and item.raw_html:
                debug_name = f"{idx:02d}_{_safe_filename(item.title)}_raw_preview.html"
                debug_path = os.path.join(OUTPUT_DIR, debug_name)
                with open(debug_path, "w", encoding="utf-8") as debug_file:
                    debug_file.write((item.raw_html or "")[:5000])
                print(f"    raw_preview_saved_to: {debug_path}")
            print(f"    saved_to: {file_path}")
            print()
    finally:
        db.close()

if __name__ == "__main__":
    main()
