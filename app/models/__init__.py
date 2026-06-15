from app.database import Base  # 从 database 模块导入 Base，确保 Alembic 等工具能识别
from app.models.source import Source  # 导入 Source 模型类，便于集中导出
from app.models.article import Article  # 导入 Article 模型类，便于集中导出
from app.models.brief import Brief  # 导入 Brief 模型类，便于集中导出
