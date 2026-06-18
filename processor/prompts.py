def build_glm_filter_prompt(title: str, first_paragraph: str, topic: str, filter_groups: list[list[str]]) -> str:  # 构建第一步筛选提示词
    group_lines = "\n".join(
        f"- {' + '.join(group)}" for group in filter_groups if group
    ) or f"- {topic}"  # 将主题和关键词组合整理成可读列表
    return f"""
你是一名信息筛选专家。请根据文章标题和首段内容，判断文章是否与下面任意一组筛选词相关。

筛选规则：
1. 主题是必须条件，关键词是可选增强条件。
2. 只要文章明显符合下列任意一组筛选词，就可以判定为 relevant=true。
3. 如果文章与这些筛选词整体无关，返回 relevant=false。
4. 请给出 0-100 的相关性评分。
5. 只返回 JSON，不要输出任何额外解释文本。

筛选词组合：
{group_lines}

返回 JSON 格式：
{{
  "relevant": true,
  "score": 80,
  "reason": "判断原因"
}}

文章标题：{title}
首段内容：{first_paragraph}
"""


def build_glm_classify_prompt(title: str, tags: str) -> str:  # 构建第三步分类提示词
    return f"""
你是一名专业内容分类专家。请根据文章标题与标签，为文章分配一个中文主题分类。

要求：
1. 主题分类示例：大模型、AI应用、行业动态、技术教程等。
2. 只返回一个中文主题名称，不要输出多余文字。

标题：{title}
标签：{tags}
"""


def build_summary_prompt(content: str) -> str:  # 构建第二步摘要提示词
    return f"""
你是一名专业内容摘要师。请为以下文章生成结构化摘要。

要求：
1. 必须使用中文输出，one_liner、key_points、tags 全部使用中文。
2. 只返回 JSON，不要输出任何额外解释文本。

返回 JSON 格式：
{{
  "one_liner": "一句话总结（中文）",
  "key_points": ["要点1（中文）", "要点2（中文）"],
  "tags": ["标签1（中文）", "标签2（中文）"]
}}

文章内容：{content}
"""
