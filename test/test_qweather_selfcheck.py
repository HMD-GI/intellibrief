# 本文件用于对和风天气接入进行“真实环境自检”。  # 说明文件功能。
# 本文件的作用是帮助人工快速判断当前 `.env` 中的和风天气配置是否正确。  # 说明文件作用。
# 自检范围包括：API Key、API Host、GeoAPI 城市查询、分时天气、预警接口以及完整天气报告。  # 说明自检内容。
# 本文件不是 mock 单元测试，而是偏人工联调脚本。  # 说明脚本定位。
# 使用方式：在项目根目录执行 `.\venv\Scripts\python.exe test\test_qweather_selfcheck.py 北京`。  # 说明运行方法。

from __future__ import annotations  # 开启注解延迟求值，便于类型标注。

import sys  # 导入系统模块，用于读取命令行参数。
from pathlib import Path  # 导入路径模块，用于补充项目根目录到导入路径。

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # 计算项目根目录。
sys.path.insert(0, str(PROJECT_ROOT))  # 将项目根目录加入导入路径，保证脚本可独立执行。

from app.config import settings  # 导入项目配置，用于读取和风天气环境变量。
from app.services.weather_service import QWeatherService, WeatherServiceError  # 导入和风天气服务及统一异常。


def _print_section(title: str) -> None:  # 定义分节打印函数。
    """打印分节标题。"""  # 说明函数作用。

    print(f"\n{'=' * 16} {title} {'=' * 16}")  # 打印醒目的分隔标题。


def _print_kv(label: str, value) -> None:  # 定义键值打印函数。
    """打印单行键值信息。"""  # 说明函数作用。

    print(f"{label}: {value}")  # 统一输出格式，便于人工查看。


def check_env_config() -> None:  # 定义环境配置检查函数。
    """检查和风天气相关环境变量。"""  # 说明函数作用。

    _print_section("配置检查")  # 打印配置检查分节标题。
    _print_kv("QWEATHER_API_KEY 是否存在", bool(settings.QWEATHER_API_KEY.strip()))  # 输出是否配置了 API Key。
    _print_kv("QWEATHER_GEO_BASE_URL", settings.QWEATHER_GEO_BASE_URL)  # 输出 GeoAPI Host。
    _print_kv("QWEATHER_API_BASE_URL", settings.QWEATHER_API_BASE_URL)  # 输出天气 API Host。
    _print_kv("WEATHER_PROVIDER", settings.WEATHER_PROVIDER)  # 输出当前天气源模式。
    if not settings.QWEATHER_API_KEY.strip():  # 如果未配置 Key。
        raise SystemExit("未配置 QWEATHER_API_KEY，无法继续执行和风天气自检。")  # 直接终止并给出明确提示。


def check_lookup(service: QWeatherService, region: str) -> dict:  # 定义城市查询检查函数。
    """检查 GeoAPI 城市查询。"""  # 说明函数作用。

    _print_section("城市查询")  # 打印城市查询分节标题。
    locations = service._lookup_locations(region)  # 调用 GeoAPI 查询地区。
    if not locations:  # 如果没有任何候选结果。
        raise WeatherServiceError(f"GeoAPI 未返回地区“{region}”的候选位置。")  # 抛出明确异常。
    location = service._normalize_location_item(locations[0], match_count=len(locations))  # 归一化首个候选位置。
    _print_kv("候选数量", len(locations))  # 输出候选数量。
    _print_kv("首个地区 ID", location.get("id"))  # 输出地区编码。
    _print_kv("首个地区名称", location.get("name"))  # 输出地区名称。
    _print_kv("首个地区展示名", location.get("display_name"))  # 输出展示名称。
    _print_kv("纬度", location.get("lat"))  # 输出纬度。
    _print_kv("经度", location.get("lon"))  # 输出经度。
    return location  # 返回归一化后的地区信息。


def check_hourly_weather(service: QWeatherService, location: dict) -> None:  # 定义分时天气检查函数。
    """检查逐小时天气接口。"""  # 说明函数作用。

    _print_section("分时天气")  # 打印分时天气分节标题。
    hourly_items = service._fetch_hourly_weather(location["id"])  # 根据 location id 查询逐小时天气。
    _print_kv("分时记录数量", len(hourly_items))  # 输出分时记录总数。
    if hourly_items:  # 如果返回了分时记录。
        first_item = hourly_items[0]  # 取第一条记录便于快速查看。
        _print_kv("首条时间", first_item.get("fxTime"))  # 输出首条时间。
        _print_kv("首条温度", first_item.get("temp"))  # 输出首条温度。
        _print_kv("首条天气", first_item.get("text"))  # 输出首条天气文字。
        _print_kv("首条湿度", first_item.get("humidity"))  # 输出首条湿度。
        _print_kv("首条降雨量", first_item.get("precip"))  # 输出首条降雨量。
        _print_kv("首条降水概率", first_item.get("pop"))  # 输出首条降水概率。


def check_warning(service: QWeatherService, location: dict) -> None:  # 定义预警检查函数。
    """检查天气预警接口。"""  # 说明函数作用。

    _print_section("天气预警")  # 打印预警分节标题。
    warnings = service._fetch_warning(location)  # 按经纬度查询天气预警。
    _print_kv("预警数量", len(warnings))  # 输出预警数量。
    if warnings:  # 如果存在预警。
        first_item = warnings[0]  # 取第一条预警。
        _print_kv("首条预警标题", first_item.get("title"))  # 输出预警标题。
        _print_kv("首条预警级别", first_item.get("level"))  # 输出预警级别。
        _print_kv("首条预警发布时间", first_item.get("pubTime"))  # 输出预警发布时间。
    else:  # 如果不存在预警。
        print("当前地区没有返回预警数据，这不一定代表接口异常。")  # 给出说明，避免误判。


def check_full_report(service: QWeatherService, region: str) -> None:  # 定义完整天气报告检查函数。
    """检查统一天气报告输出。"""  # 说明函数作用。

    _print_section("完整报告")  # 打印完整报告分节标题。
    report = service.get_daily_weather_report(region)  # 调用统一天气报告接口。
    _print_kv("报告地区", report.get("region"))  # 输出报告地区。
    _print_kv("报告日期", report.get("date"))  # 输出报告日期。
    _print_kv("供应商", (report.get("provider") or {}).get("label"))  # 输出供应商标签。
    _print_kv("分时数量", len(report.get("hourly") or []))  # 输出分时数量。
    _print_kv("预警数量", len(report.get("warnings") or []))  # 输出预警数量。
    _print_kv("台风支持", (report.get("typhoon") or {}).get("provider_supported"))  # 输出台风能力是否可用。
    _print_kv("提示信息", report.get("notices") or [])  # 输出系统提示信息。


def main() -> int:  # 定义主函数。
    """执行和风天气自检流程。"""  # 说明函数作用。

    region = sys.argv[1].strip() if len(sys.argv) > 1 and sys.argv[1].strip() else settings.DEFAULT_WEATHER_REGION  # 读取命令行地区参数，未传则使用默认地区。
    service = QWeatherService()  # 创建和风天气服务实例。
    try:  # 进入自检主流程。
        check_env_config()  # 检查环境变量。
        _print_kv("本次自检地区", region)  # 输出本次测试地区。
        location = check_lookup(service, region)  # 检查城市查询。
        check_hourly_weather(service, location)  # 检查逐小时天气。
        check_warning(service, location)  # 检查天气预警。
        check_full_report(service, region)  # 检查统一报告。
        _print_section("自检结果")  # 打印结果分节标题。
        print("和风天气自检通过。")  # 输出成功结论。
        return 0  # 返回成功退出码。
    except WeatherServiceError as exc:  # 捕获和风天气业务异常。
        _print_section("自检结果")  # 打印结果分节标题。
        print(f"和风天气自检失败：{exc}")  # 输出失败原因。
        return 1  # 返回失败退出码。
    except Exception as exc:  # 捕获未知异常。
        _print_section("自检结果")  # 打印结果分节标题。
        print(f"和风天气自检出现未预期异常：{exc}")  # 输出未知异常信息。
        return 2  # 返回异常退出码。


if __name__ == "__main__":  # 判断是否以脚本方式直接运行。
    raise SystemExit(main())  # 执行主函数并按返回码退出。
