from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger


class RuntimeScheduler:
    """统一管理应用内的 APScheduler 调度器。

    技术说明：
    1. 这里使用 APScheduler 的 BackgroundScheduler，在 FastAPI 进程内维护定时任务。
    2. 相比 threading.Timer，APScheduler 更适合管理多条可编辑、可恢复的周期任务。
    3. 当前项目的定时规则保存在数据库中，应用启动后会从数据库恢复为 APScheduler Job。
    """

    def __init__(self) -> None:
        # 使用上海时区，确保前端输入的 HH:mm 与后端触发时间保持一致。
        self._scheduler = BackgroundScheduler(timezone=ZoneInfo("Asia/Shanghai"))
        self._started = False

    def start(self) -> None:
        """启动调度器。"""

        if self._started:
            return
        self._scheduler.start()
        self._started = True

    def shutdown(self) -> None:
        """关闭调度器。"""

        if not self._started:
            return
        self._scheduler.shutdown(wait=False)
        self._started = False

    def upsert_daily_job(self, job_id: str, func, time_text: str, args: tuple | None = None) -> None:
        """按天更新或创建一个固定时间任务。

        技术原理：
        1. 通过 CronTrigger(hour, minute) 表示“每天某个时刻执行一次”。
        2. 使用 replace_existing=True 可以确保同一个 job_id 的配置被覆盖，而不是重复注册。
        """

        hour, minute = [int(part) for part in time_text.split(":", 1)]
        self._scheduler.add_job(
            func=func,
            trigger=CronTrigger(hour=hour, minute=minute, timezone=ZoneInfo("Asia/Shanghai")),
            id=job_id,
            args=list(args or ()),
            replace_existing=True,
            misfire_grace_time=300,
            coalesce=True,
        )

    def remove_job(self, job_id: str) -> None:
        """移除单个任务。"""

        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)

    def remove_jobs_by_prefix(self, prefix: str) -> None:
        """按前缀批量移除任务。"""

        for job in self._scheduler.get_jobs():
            if job.id.startswith(prefix):
                self._scheduler.remove_job(job.id)


runtime_scheduler = RuntimeScheduler()
