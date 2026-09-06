#!/usr/bin/env python3
"""oss_upload 单元测试（不连真实 OSS：mock 模式 + fake oss2 注入）

覆盖：配置判定 / key 规范 / mock 上传 / 真实上传（含重试与失败上抛）/
oss2 未安装时的明确报错。
运行：python3 daemon/test_oss_upload.py
"""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oss_upload  # noqa: E402


def make_fake_oss2(behavior):
    """构造 fake oss2 模块：Auth/Bucket；Bucket.put_object_from_file 按 behavior 执行。

    behavior: callable(key, path) 或异常（由调用方控制第几次抛错）
    """
    calls = []

    class FakeBucket:
        def __init__(self, auth, endpoint, bucket):
            self.auth, self.endpoint, self.bucket = auth, endpoint, bucket

        def put_object_from_file(self, key, path):
            calls.append((key, path))
            return behavior(key, path)

    return types.SimpleNamespace(
        Auth=lambda ak, sk: (ak, sk),
        Bucket=FakeBucket,
        calls=calls,
    )


class OssUploadTest(unittest.TestCase):
    def setUp(self):
        # 干净环境（避免本机 .env/真实变量干扰）
        for k in list(os.environ):
            if k.startswith("OSS_") or k.startswith("ALIBABA_CLOUD_") or k.startswith("BOOKMADE_OSS"):
                os.environ.pop(k, None)
        oss_upload.BACKOFF_BASE_S = 0.001  # 测重试不真等

    def tearDown(self):
        for k in list(os.environ):
            if k.startswith("OSS_") or k.startswith("ALIBABA_CLOUD_") or k.startswith("BOOKMADE_OSS"):
                os.environ.pop(k, None)

    def test_未配置返回None(self):
        self.assertIsNone(oss_upload.get_uploader({}))

    def test_key规范(self):
        self.assertEqual(oss_upload.object_key("BM-ABC1"), "orders/BM-ABC1.mp3")

    def test_mock上传成功(self):
        uploader = oss_upload.get_uploader({"BOOKMADE_OSS_MOCK": "1"})
        self.assertIsNotNone(uploader)
        with tempfile.NamedTemporaryFile(suffix=".mp3") as f:
            f.write(b"x" * 10)
            f.flush()
            key = uploader("BM-MOCK1", f.name)
        self.assertEqual(key, "orders/BM-MOCK1.mp3")

    def test_mock产物缺失报错(self):
        uploader = oss_upload.get_uploader({"BOOKMADE_OSS_MOCK": "1"})
        with self.assertRaises(FileNotFoundError):
            uploader("BM-MOCK2", "/nonexistent/xx.mp3")

    def test_真实上传成功(self):
        fake = make_fake_oss2(lambda key, path: "etag-ok")

        def run():
            with mock.patch.dict(sys.modules, {"oss2": fake}):
                return oss_upload.get_uploader({
                    "OSS_ENDPOINT": "https://oss-cn-hongkong.aliyuncs.com",
                    "OSS_BUCKET": "bookmadebook-audio",
                    "OSS_AK_ID": "ak", "OSS_AK_SECRET": "sk",
                })("BM-REAL1", "/tmp/x.mp3")

        key = run()
        self.assertEqual(key, "orders/BM-REAL1.mp3")
        self.assertEqual(fake.calls, [("orders/BM-REAL1.mp3", "/tmp/x.mp3")])

    def test_真实上传先败后成(self):
        state = {"n": 0}

        def flaky(key, path):
            state["n"] += 1
            if state["n"] < 3:
                raise OSError("net down")
            return "etag"

        fake = make_fake_oss2(flaky)
        cfg = {"OSS_ENDPOINT": "https://oss-cn-hongkong.aliyuncs.com",
               "OSS_BUCKET": "b", "OSS_AK_ID": "ak", "OSS_AK_SECRET": "sk"}
        with mock.patch.object(oss_upload.time, "sleep", lambda s: None), \
             mock.patch.dict(sys.modules, {"oss2": fake}):
            uploader = oss_upload.get_uploader(cfg)
            self.assertEqual(uploader("BM-RETRY1", "/tmp/x.mp3"), "orders/BM-RETRY1.mp3")
        self.assertEqual(state["n"], 3)  # 2 败 + 1 成

    def test_重试耗尽抛错(self):
        fake = make_fake_oss2(lambda key, path: (_ for _ in ()).throw(OSError("always down")))
        cfg = {"OSS_ENDPOINT": "https://oss-cn-hongkong.aliyuncs.com",
               "OSS_BUCKET": "b", "OSS_AK_ID": "ak", "OSS_AK_SECRET": "sk",
               "retries": 3}
        with mock.patch.object(oss_upload.time, "sleep", lambda s: None), \
             mock.patch.dict(sys.modules, {"oss2": fake}):
            uploader = oss_upload.get_uploader(cfg)
            with self.assertRaises(RuntimeError) as ctx:
                uploader("BM-FAIL1", "/tmp/x.mp3")
        self.assertIn("已重试 3 次", str(ctx.exception))
        self.assertEqual(len(fake.calls), 3)

    def test_oss2未安装明确报错(self):
        cfg = {"OSS_ENDPOINT": "https://oss-cn-hongkong.aliyuncs.com",
               "OSS_BUCKET": "b", "OSS_AK_ID": "ak", "OSS_AK_SECRET": "sk"}
        with mock.patch.dict(sys.modules, {"oss2": None}):  # import oss2 → ImportError
            uploader = oss_upload.get_uploader(cfg)
            with self.assertRaises(RuntimeError) as ctx:
                uploader("BM-NOOSS1", "/tmp/x.mp3")
        self.assertIn("pip install oss2", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
