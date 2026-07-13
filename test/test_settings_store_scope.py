import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.common.settings_store import build_setting_storage_key, normalize_user_key


class SettingsStoreScopeTests(unittest.TestCase):
    """验证按用户隔离的设置键生成逻辑。"""

    def test_scoped_keys_include_user_key(self):
        # 发送设置属于按用户隔离配置，实际存储键中应包含用户标识。
        self.assertEqual(
            build_setting_storage_key("bindings", "alice"),
            "bindings::user::alice",
        )

    def test_empty_user_key_falls_back_to_default(self):
        # 当请求头中没有传用户标识时，应回退到 default，保证旧逻辑可用。
        self.assertEqual(normalize_user_key(""), "default")
        self.assertEqual(build_setting_storage_key("bindings", ""), "bindings::user::default")

    def test_non_scoped_keys_remain_global(self):
        # schedule 这类全局运行配置不做用户隔离，避免定时器恢复逻辑被拆散。
        self.assertEqual(build_setting_storage_key("schedule", "alice"), "schedule")


if __name__ == "__main__":
    unittest.main()
