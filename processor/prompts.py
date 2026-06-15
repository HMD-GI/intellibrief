def build_glm_filter_prompt(title: str, first_paragraph: str, topics: str) -> str:  # 构建 GLM 筛选提示词
    return f"""
你是一个信息筛选专家。请根据文章标题和首段内容，判断文章与指定主题的相关性。

要求：
1) 判断文章是否与主题"{topics}"相关。
2) 给出 0-100 的相关性评分。
3) 只返回 JSON，不要输出任何额外解释文本。

返回 JSON 格式：
{{
    "relevant": true,
    "score": 80,
    "reason": "判断原因"
}}

文章标题：{title}
首段：{first_paragraph}
"""


def build_glm_classify_prompt(title: str, tags: str) -> str:  # 构建 GLM 分类提示词
    return f"""
你是一个专业内容分类专家。
请根据文章标题与标签，为文章分配一个中文主题分类。

要求：
1) 主题分类示例：大模型、AI应用、行业动态、技术教程等。
2) 只返回一个中文主题名称，不要输出多余文字。

标题：{title}
标签：{tags}
"""


def build_summary_prompt(content: str) -> str:  # 构建 DeepSeek 摘要提示词
    return f"""
你是一个专业内容摘要师。请为以下文章生成结构化摘要。

要求：
1) 必须使用中文输出（one_liner、key_points、tags 全部为中文）。
2) 只返回 JSON，不要输出任何额外解释文本。

返回 JSON 格式：
{{
    "one_liner": "一句话总结（中文）",
    "key_points": ["要点1（中文）", "要点2（中文）"],
    "tags": ["标签1（中文）", "标签2（中文）"]
}}

文章内容：{content}
"""
