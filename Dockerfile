FROM python:3.10-slim
# 基础镜像使用轻量级的 Python 3.10

WORKDIR /app
# 设置工作目录为 /app

# 安装系统基础依赖（用于编译某些 Python 扩展）
RUN apt-get update && apt-get install -y \
    build-essential \
    libxml2-dev \
    libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

# 复制 Python 依赖列表文件
COPY requirements.txt .
# 安装 Python 依赖，--no-cache-dir 避免缓存以减小镜像体积
RUN pip install --no-cache-dir -r requirements.txt

# 安装 Playwright 需要的浏览器二进制文件 (仅安装 chromium)
RUN playwright install chromium
# 安装 Chromium 运行所需的系统依赖
RUN playwright install-deps chromium

# 复制项目所有代码到容器内
COPY . .

# 如果使用 SQLite，需要预先创建 data 文件夹防止报错
RUN mkdir -p /app/data

# 设置 PYTHONPATH 环境变量，确保模块可以正确导入
ENV PYTHONPATH=/app

# 默认启动命令：运行 FastAPI 后端服务
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
