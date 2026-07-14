import argparse  # 导入命令行参数模块，用于解析导出与导入模式、路径和开关参数。
import json  # 导入 JSON 模块，用于将数据库记录和 Redis 键值序列化到文件中。
import shutil  # 导入文件复制模块，用于复制 digest 和 photo 目录到打包目录。
from datetime import date, datetime  # 导入日期时间类型，用于序列化与反序列化日期字段。
from enum import Enum  # 导入枚举基类，用于兼容 SQLAlchemy 枚举字段的 JSON 序列化。
from pathlib import Path  # 导入路径类，用于跨平台处理目录与文件路径。

import bootstrap  # 导入测试引导模块，确保脚本从 test 目录运行时也能找到项目根路径。
import redis  # 导入 Redis 客户端库，用于直接读取和恢复 Redis 原始键值。
from sqlalchemy import text  # 导入原生 SQL 构造器，用于在 PostgreSQL 中重置序列。

from app.config import settings  # 导入项目配置，用于读取数据库地址与 Redis 连接地址。
from app.database import SessionLocal  # 导入数据库会话工厂，用于读写 PostgreSQL 数据。
from app.models.article import Article  # 导入文章表模型，用于导出和导入文章数据。
from app.models.brief import Brief  # 导入简报表模型，用于导出和导入简报数据。
from app.models.brief_run import ArticleRun, BriefRun  # 导入运行隔离表模型，用于导出和导入 AI 运行结果。
from app.models.cache_entry import CacheEntry  # 导入缓存兜底表模型，用于导出和导入 PostgreSQL 持久化缓存。
from app.models.setting import AppSetting  # 导入应用设置表模型，用于导出和导入前端绑定、定时设置等配置。
from app.models.source import Source  # 导入数据源表模型，用于导出和导入可爬取的数据源配置。


PROJECT_ROOT = Path(__file__).resolve().parents[1]  # 定义项目根目录，后续复制 digest 和 photo 时统一复用。
DEFAULT_BUNDLE_DIR = PROJECT_ROOT / "test" / "runtime_bundle"  # 定义默认导出目录，集中存放打包结果。
TABLE_EXPORT_ORDER = [Source, Article, BriefRun, ArticleRun, Brief, AppSetting, CacheEntry]  # 定义导出顺序，便于阅读和导入时保持依赖关系。
TABLE_IMPORT_CLEAR_ORDER = [Brief, ArticleRun, BriefRun, Article, Source, AppSetting, CacheEntry]  # 定义导入前清空顺序，优先清理依赖方，避免外键冲突。
TABLE_SEQUENCE_RESET_ORDER = ["sources", "articles", "brief_runs", "article_runs", "briefs", "app_settings", "cache_entries"]  # 定义需要重置主键序列的表名列表。
FILE_DIRECTORIES = ["digest", "photo"]  # 定义运行时静态目录列表，导出和导入时统一复制。


def print_separator(title: str) -> None:  # 定义分隔线打印函数，title 表示当前步骤名称。
    print("\n" + "=" * 72)  # 打印上边框，提升终端输出层次感。
    print(f"  {title}")  # 打印步骤标题，帮助用户快速识别当前执行阶段。
    print("=" * 72)  # 打印下边框，形成完整视觉块。


def _to_jsonable(value):  # 定义通用序列化函数，value 表示任意数据库字段值。
    if isinstance(value, Enum):  # 如果字段值是枚举对象，则转换成其 value 文本，避免 JSON 无法直接编码。
        return value.value  # 返回枚举实际存储值，例如 pending、processed。
    if isinstance(value, datetime):  # 如果字段值是 datetime，则转换为 ISO 字符串。
        return value.isoformat()  # 返回标准时间字符串，便于导入时恢复。
    if isinstance(value, date):  # 如果字段值是 date，则也转换成 ISO 字符串。
        return value.isoformat()  # 返回日期字符串，例如 2026-07-13。
    return value  # 其他普通类型原样返回，交给 JSON 模块直接处理。


def _model_to_dict(row) -> dict:  # 定义 ORM 记录转字典函数，row 表示单条 SQLAlchemy 模型记录。
    payload = {}  # 初始化结果字典，用于承接当前记录的所有列值。
    for column in row.__table__.columns:  # 遍历模型定义中的每一列，保证导出字段完整且稳定。
        payload[column.name] = _to_jsonable(getattr(row, column.name))  # 按列名读取字段值并做 JSON 兼容转换。
    return payload  # 返回可直接写入 JSON 的字典对象。


def _restore_scalar_value(column, value):  # 定义标量恢复函数，column 是列对象，value 是 JSON 中的原始值。
    if value is None:  # 如果导出值本来就是空，则无需做额外处理。
        return None  # 直接返回空值，交给 ORM 写入数据库。
    python_type = getattr(column.type, "python_type", None)  # 尝试读取列对应的 Python 类型，用于区分日期和整数等场景。
    try:  # 用 try 包裹，避免个别列类型没有 python_type 属性时中断导入。
        if python_type is datetime and isinstance(value, str):  # 如果目标类型是 datetime 且当前值是字符串，则恢复为 datetime 对象。
            return datetime.fromisoformat(value)  # 使用 ISO 格式反序列化为 datetime。
        if python_type is date and isinstance(value, str):  # 如果目标类型是 date 且当前值是字符串，则恢复为 date 对象。
            return date.fromisoformat(value)  # 使用 ISO 格式反序列化为 date。
    except Exception:  # 如果反序列化异常，则退回原值，让后续写库时暴露真实错误。
        return value  # 返回原始值，避免在这里吞掉有效排查信息。
    return value  # 普通类型直接返回，不做额外转换。


def _dict_to_model(model_cls, payload: dict):  # 定义字典恢复为模型实例函数，model_cls 是模型类，payload 是单条记录字典。
    converted = {}  # 初始化转换后的字段字典，用于构造 ORM 对象。
    for column in model_cls.__table__.columns:  # 遍历模型列，逐列恢复类型。
        if column.name in payload:  # 仅处理导出中实际存在的字段，兼容未来字段新增或减少。
            converted[column.name] = _restore_scalar_value(column, payload[column.name])  # 恢复字段值类型并写入新字典。
    return model_cls(**converted)  # 返回构造好的 ORM 对象实例，供后续批量入库。


def _open_db():  # 定义数据库会话创建函数，用于统一所有导入导出步骤的连接方式。
    return SessionLocal()  # 创建并返回独立数据库会话。


def _open_redis_client() -> redis.Redis | None:  # 定义 Redis 直连函数，用于原样导出和导入 Redis 键值。
    try:  # 使用 try/except 捕获 Redis 未启动或密码错误等异常。
        client = redis.from_url(settings.REDIS_URL, decode_responses=True)  # 按项目环境变量创建 Redis 客户端，并以字符串形式读写内容。
        client.ping()  # 主动探活，确认 Redis 当前可连通。
        return client  # Redis 可用时返回客户端对象。
    except Exception as exc:  # 捕获任意连接异常，避免因为 Redis 不可用导致整个打包流程失败。
        print(f"Redis 连接失败，本次跳过 Redis 导出/导入：{exc}")  # 输出提示，说明 Redis 数据不会参与本次流程。
        return None  # 返回空值，调用方看到后自动跳过 Redis 步骤。


def export_database(bundle_dir: Path) -> None:  # 定义数据库导出函数，bundle_dir 表示当前打包输出目录。
    db = _open_db()  # 创建数据库会话，用于查询所有需要导出的表。
    try:  # 使用 try/finally 保证导出结束后关闭连接。
        db_payload = {}  # 初始化数据库总导出结果，键为表名，值为记录列表。
        for model_cls in TABLE_EXPORT_ORDER:  # 按既定顺序遍历所有需要导出的模型类。
            rows = db.query(model_cls).all()  # 查询当前表全部记录，准备序列化输出。
            db_payload[model_cls.__tablename__] = [_model_to_dict(row) for row in rows]  # 将当前表记录列表转为可 JSON 序列化的字典列表。
            print(f"已导出表 {model_cls.__tablename__}：{len(rows)} 条")  # 输出当前表导出条数，便于核对结果。

        db_file = bundle_dir / "postgres_data.json"  # 计算数据库导出文件路径，统一写入单个 JSON 文件。
        db_file.write_text(json.dumps(db_payload, ensure_ascii=False, indent=2), encoding="utf-8")  # 将全部表数据写入 JSON 文件，并保留中文。
        print(f"PostgreSQL 数据已写入：{db_file}")  # 输出导出文件路径，方便用户查看与上传。
    finally:  # finally 中统一关闭数据库会话。
        db.close()  # 释放数据库连接资源。


def export_redis(bundle_dir: Path) -> None:  # 定义 Redis 导出函数，bundle_dir 表示打包输出目录。
    client = _open_redis_client()  # 尝试连接 Redis 客户端，如果失败则后续直接跳过。
    if client is None:  # 如果 Redis 当前不可用，则不给出空文件，直接结束导出。
        return  # 提前退出 Redis 导出流程。

    redis_payload = {}  # 初始化 Redis 导出结果字典，键为 Redis key，值为类型、TTL 和内容。
    for key in client.scan_iter("*"):  # 遍历 Redis 中全部键，scan_iter 可避免一次性拉全量阻塞服务器。
        key_type = client.type(key)  # 读取当前键的 Redis 数据类型，例如 string/list/set/hash/zset。
        ttl = client.ttl(key)  # 读取当前键剩余 TTL，便于导入时尽量恢复失效时间。
        if key_type == "string":  # 如果是字符串键，则直接读取单值。
            value = client.get(key)  # 获取字符串内容。
        elif key_type == "list":  # 如果是列表键，则读取全部列表内容。
            value = client.lrange(key, 0, -1)  # 获取列表所有元素，保持原始顺序。
        elif key_type == "set":  # 如果是集合键，则读取全部成员。
            value = sorted(list(client.smembers(key)))  # 将集合转成排序列表，保证导出文件稳定可比对。
        elif key_type == "hash":  # 如果是哈希键，则读取全部字段和值。
            value = client.hgetall(key)  # 获取完整哈希内容。
        elif key_type == "zset":  # 如果是有序集合键，则读取成员和分值。
            value = client.zrange(key, 0, -1, withscores=True)  # 获取有序集合全量数据及分值。
        else:  # 如果遇到当前脚本未覆盖的 Redis 类型，则保守跳过并提示。
            print(f"跳过暂不支持的 Redis 类型：key={key} type={key_type}")  # 输出跳过信息，防止用户误以为已完整导出。
            continue  # 进入下一个键的处理。
        redis_payload[key] = {"type": key_type, "ttl": ttl, "value": value}  # 将当前键的类型、剩余 TTL 和内容写入导出结果。

    redis_file = bundle_dir / "redis_data.json"  # 计算 Redis 导出文件路径。
    redis_file.write_text(json.dumps(redis_payload, ensure_ascii=False, indent=2), encoding="utf-8")  # 将 Redis 数据写入 JSON 文件。
    print(f"Redis 数据已写入：{redis_file}")  # 输出 Redis 导出文件路径，方便用户后续上传到服务器。


def export_runtime_files(bundle_dir: Path) -> None:  # 定义运行时静态文件导出函数，bundle_dir 表示打包输出目录。
    files_root = bundle_dir / "runtime_files"  # 计算运行时静态文件打包根目录。
    files_root.mkdir(parents=True, exist_ok=True)  # 创建运行时文件打包目录，若已存在则直接复用。
    for directory_name in FILE_DIRECTORIES:  # 依次处理 digest 和 photo 两个运行时目录。
        source_dir = PROJECT_ROOT / directory_name  # 计算本地原始目录路径。
        target_dir = files_root / directory_name  # 计算打包目录中的目标路径。
        if not source_dir.exists():  # 如果原始目录不存在，则提示并跳过，不视为错误。
            print(f"目录不存在，跳过导出：{source_dir}")  # 输出跳过提示，方便用户确认当前环境是否已有运行时文件。
            continue  # 进入下一个目录处理。
        if target_dir.exists():  # 如果目标目录已存在，则先删除旧目录，避免残留旧文件影响打包结果。
            shutil.rmtree(target_dir)  # 删除旧的打包目标目录。
        shutil.copytree(source_dir, target_dir)  # 递归复制整个目录到打包输出目录，保留所有简报和图片文件。
        print(f"已复制目录：{source_dir} -> {target_dir}")  # 输出目录复制结果，便于核对导出完整性。


def export_bundle(bundle_dir: Path) -> None:  # 定义总导出函数，bundle_dir 表示统一打包目录。
    print_separator("导出本地 PostgreSQL、Redis 与运行时文件")  # 打印导出阶段标题。
    bundle_dir.mkdir(parents=True, exist_ok=True)  # 创建打包根目录，确保输出路径存在。
    export_database(bundle_dir)  # 导出 PostgreSQL 业务数据到 JSON 文件。
    export_redis(bundle_dir)  # 导出 Redis 热缓存键值到 JSON 文件。
    export_runtime_files(bundle_dir)  # 导出 digest 和 photo 两个运行时目录。
    print("导出完成。")  # 输出总导出完成提示。


def _clear_database_for_import(db) -> None:  # 定义导入前清空数据库函数，db 表示当前数据库会话。
    for model_cls in TABLE_IMPORT_CLEAR_ORDER:  # 按依赖逆序清空表数据，避免外键约束报错。
        db.query(model_cls).delete()  # 删除当前表全部数据，准备导入新的完整快照。
    db.commit()  # 提交清空事务，使数据库进入空表状态。


def _reset_postgres_sequences(db) -> None:  # 定义 PostgreSQL 自增序列重置函数，db 表示当前数据库会话。
    if not settings.DATABASE_URL.startswith("postgresql"):  # 如果当前环境不是 PostgreSQL，则无需执行序列重置。
        return  # 直接返回，避免在其他数据库方言下执行不兼容 SQL。
    for table_name in TABLE_SEQUENCE_RESET_ORDER:  # 逐个遍历需要重置序列的表名。
        db.execute(  # 执行 PostgreSQL 原生 SQL，按表内最大 id 调整序列当前值。
            text(
                f"""
                SELECT setval(
                    pg_get_serial_sequence('{table_name}', 'id'),
                    COALESCE((SELECT MAX(id) FROM {table_name}), 1),
                    true
                )
                """
            )
        )
    db.commit()  # 提交序列重置事务，确保后续新增数据不会主键冲突。


def import_database(bundle_dir: Path, clear_first: bool) -> None:  # 定义数据库导入函数，bundle_dir 表示数据包目录，clear_first 表示是否先清空现有数据。
    db_file = bundle_dir / "postgres_data.json"  # 计算数据库 JSON 文件路径。
    if not db_file.exists():  # 如果数据库导出文件不存在，则直接抛错，避免误导用户。
        raise FileNotFoundError(f"未找到数据库导出文件：{db_file}")  # 抛出明确错误，提示用户检查上传是否完整。

    payload = json.loads(db_file.read_text(encoding="utf-8"))  # 读取 JSON 文件并解析为字典对象。
    db = _open_db()  # 创建数据库会话，用于导入全部表数据。
    try:  # 使用事务保护数据库导入过程。
        if clear_first:  # 如果用户要求先清空服务器现有数据，则先执行清空逻辑。
            _clear_database_for_import(db)  # 清空相关表内容，为恢复完整快照做准备。
            print("导入前已清空服务器数据库中的相关业务表。")  # 输出清空提示，便于确认行为。

        for model_cls in TABLE_EXPORT_ORDER:  # 按固定顺序恢复每张表，保证外键依赖正确。
            table_name = model_cls.__tablename__  # 提取当前模型对应的表名，作为 JSON 键名。
            records = payload.get(table_name, [])  # 从导出文件中读取当前表的数据列表，若不存在则视为空。
            for record in records:  # 遍历当前表每一条导出记录。
                db.add(_dict_to_model(model_cls, record))  # 将字典恢复为 ORM 对象后加入当前会话。
            db.commit()  # 每张表单独提交一次，便于定位具体是哪张表导入失败。
            print(f"已导入表 {table_name}：{len(records)} 条")  # 输出当前表导入条数，便于和本地导出核对。

        _reset_postgres_sequences(db)  # 导入完成后重置主键序列，避免后续新增时出现重复主键。
        print("PostgreSQL 数据导入完成。")  # 输出数据库导入成功提示。
    except Exception:  # 捕获导入期间的异常，统一回滚事务。
        db.rollback()  # 回滚当前未提交事务，避免导入到一半留下脏数据。
        raise  # 继续抛出异常，让调用方得到真实错误信息。
    finally:  # finally 块无论成功失败都要关闭数据库会话。
        db.close()  # 关闭数据库连接。


def import_redis(bundle_dir: Path) -> None:  # 定义 Redis 导入函数，bundle_dir 表示数据包目录。
    redis_file = bundle_dir / "redis_data.json"  # 计算 Redis 导出文件路径。
    if not redis_file.exists():  # 如果导出包中没有 Redis 文件，则直接跳过，不视为失败。
        print("未找到 Redis 导出文件，跳过 Redis 导入。")  # 输出提示，说明本次只恢复数据库和静态文件。
        return  # 直接返回。

    client = _open_redis_client()  # 尝试连接目标服务器 Redis，用于恢复热缓存数据。
    if client is None:  # 如果 Redis 当前不可用，则跳过导入，避免影响其它数据恢复。
        return  # 提前结束 Redis 导入流程。

    payload = json.loads(redis_file.read_text(encoding="utf-8"))  # 读取 Redis 导出 JSON 文件。
    for key, item in payload.items():  # 遍历每一个导出的 Redis key，逐个恢复。
        key_type = item.get("type")  # 读取当前键的数据类型，用于选择正确的恢复命令。
        ttl = item.get("ttl", -1)  # 读取剩余 TTL，后续恢复后尽量补回过期时间。
        value = item.get("value")  # 读取当前键的实际内容。
        client.delete(key)  # 导入前先删除同名旧键，避免类型冲突或旧内容残留。
        if key_type == "string":  # 如果是字符串键，则直接写入字符串值。
            client.set(key, value)  # 使用 set 写入字符串。
        elif key_type == "list":  # 如果是列表键，则按原顺序恢复列表内容。
            if value:  # 只有列表非空时才执行 rpush，避免空列表没有意义。
                client.rpush(key, *value)  # 用 rpush 恢复列表原顺序。
        elif key_type == "set":  # 如果是集合键，则批量恢复集合成员。
            if value:  # 仅在集合非空时执行 sadd。
                client.sadd(key, *value)  # 将集合成员一次性写回 Redis。
        elif key_type == "hash":  # 如果是哈希键，则恢复全部字段和值。
            if value:  # 只有哈希非空时才执行 hset 映射恢复。
                client.hset(key, mapping=value)  # 批量恢复哈希内容。
        elif key_type == "zset":  # 如果是有序集合键，则恢复成员及其分值。
            if value:  # 仅在 zset 非空时执行恢复。
                client.zadd(key, {member: score for member, score in value})  # 将成员和分值映射恢复回 Redis。
        else:  # 如果是当前脚本不支持的键类型，则跳过并继续处理其它键。
            print(f"跳过暂不支持的 Redis 类型：key={key} type={key_type}")  # 输出跳过信息，便于用户了解实际恢复范围。
            continue  # 继续下一个键。

        if isinstance(ttl, int) and ttl > 0:  # 如果导出时该键存在剩余有效期，则在恢复后重新设置 TTL。
            client.expire(key, ttl)  # 恢复原始过期时间，尽量保持本地 Redis 状态一致。
    print("Redis 数据导入完成。")  # 输出 Redis 导入成功提示。


def import_runtime_files(bundle_dir: Path, replace_files: bool) -> None:  # 定义静态目录导入函数，replace_files 表示是否覆盖服务器现有目录。
    files_root = bundle_dir / "runtime_files"  # 计算导出包中的运行时静态文件根目录。
    if not files_root.exists():  # 如果导出包中没有运行时目录，则直接跳过。
        print("未找到 runtime_files 目录，跳过 digest/photo 导入。")  # 输出跳过提示，说明本次仅恢复数据库与缓存。
        return  # 结束静态目录导入流程。

    for directory_name in FILE_DIRECTORIES:  # 依次处理 digest 和 photo 目录。
        source_dir = files_root / directory_name  # 计算导出包中当前目录的路径。
        target_dir = PROJECT_ROOT / directory_name  # 计算服务器项目中的目标目录路径。
        if not source_dir.exists():  # 如果导出包里没有该目录，则跳过该项。
            print(f"导出包中缺少目录，跳过：{source_dir}")  # 输出跳过提示，说明某个目录本次未打包。
            continue  # 继续处理下一个目录。
        if target_dir.exists() and replace_files:  # 如果目标目录已存在且允许覆盖，则先删除旧目录。
            shutil.rmtree(target_dir)  # 删除服务器现有目录，保证导入结果与本地一致。
        if target_dir.exists() and not replace_files:  # 如果目标目录存在且不允许覆盖，则跳过，避免误删服务器现有文件。
            print(f"目标目录已存在且未开启覆盖，跳过：{target_dir}")  # 输出跳过提示，提醒用户如需覆盖请开启参数。
            continue  # 继续处理下一项。
        shutil.copytree(source_dir, target_dir)  # 复制本地打包目录到服务器项目目录，恢复 digest 和 photo 文件。
        print(f"已恢复目录：{target_dir}")  # 输出恢复成功提示，便于用户核对目录是否落盘。


def import_bundle(bundle_dir: Path, clear_first: bool, replace_files: bool) -> None:  # 定义总导入函数，负责恢复数据库、Redis 和静态目录。
    print_separator("导入 PostgreSQL、Redis 与运行时文件到当前环境")  # 打印导入阶段标题。
    import_database(bundle_dir, clear_first=clear_first)  # 先恢复数据库业务记录，保证简报列表和文章数据可查询。
    import_redis(bundle_dir)  # 再恢复 Redis 热缓存，补齐近期查询、游标和去重等运行态数据。
    import_runtime_files(bundle_dir, replace_files=replace_files)  # 最后恢复 digest 和 photo 目录，保证简报 HTML 和图片资源可访问。
    print("导入完成。")  # 输出总导入完成提示。


def main() -> int:  # 定义主函数，用于解析命令行参数并分派执行导出或导入动作。
    parser = argparse.ArgumentParser(description="导出或导入 IntelliBrief 的 PostgreSQL、Redis 和运行时文件。")  # 创建参数解析器并给出脚本用途说明。
    parser.add_argument("mode", choices=["export", "import"], help="执行模式：export 表示导出，import 表示导入。")  # 定义必填模式参数，明确区分导出与导入。
    parser.add_argument("--bundle-dir", default=str(DEFAULT_BUNDLE_DIR), help="导出或导入目录，默认使用 test/runtime_bundle。")  # 定义可选目录参数，用于指定数据包路径。
    parser.add_argument("--clear-first", action="store_true", help="导入前先清空服务器数据库中的相关业务表。")  # 定义导入前清空数据库开关，避免旧数据与新数据重复。
    parser.add_argument("--replace-files", action="store_true", help="导入时覆盖服务器现有的 digest 和 photo 目录。")  # 定义静态目录覆盖开关，控制是否替换已有文件。
    args = parser.parse_args()  # 解析用户传入参数，得到执行模式与路径配置。

    bundle_dir = Path(args.bundle_dir).resolve()  # 将用户传入路径转换为绝对路径，避免相对路径造成误判。
    if args.mode == "export":  # 如果当前模式为导出，则执行本地数据打包。
        export_bundle(bundle_dir)  # 调用总导出函数，将数据写入 bundle_dir。
    else:  # 否则当前模式为导入，需要从 bundle_dir 恢复数据到当前环境。
        import_bundle(bundle_dir, clear_first=args.clear_first, replace_files=args.replace_files)  # 调用总导入函数，按参数决定是否覆盖旧数据和旧文件。
    return 0  # 正常执行完成时返回 0 状态码。


if __name__ == "__main__":  # 仅当脚本被直接执行时才进入主函数。
    raise SystemExit(main())  # 用主函数返回值作为进程退出码，方便命令行脚本化使用。
