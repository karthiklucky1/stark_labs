import unittest

from app.services.sandbox import SandboxManager


class SandboxManagerPortInferenceTests(unittest.TestCase):
    def test_explicit_port_wins(self) -> None:
        port = SandboxManager.infer_service_port(
            "uvicorn main:app --host 0.0.0.0 --port 8111",
            health_path="/health",
        )
        self.assertEqual(port, 8111)

    def test_next_dev_defaults_to_3000(self) -> None:
        port = SandboxManager.infer_service_port("npm run dev", health_path="/")
        self.assertEqual(port, 3000)

    def test_nextjs_files_default_to_3000(self) -> None:
        port = SandboxManager.infer_service_port(
            "",
            health_path="/",
            files={"package.json": "{}", "next.config.js": "module.exports = {}"},
        )
        self.assertEqual(port, 3000)

    def test_launch_command_keeps_startup_command(self) -> None:
        command = SandboxManager()._build_launch_command("npm run dev -- --hostname 0.0.0.0 --port 3000")
        self.assertIn("exec npm run dev -- --hostname 0.0.0.0 --port 3000", command)


if __name__ == "__main__":
    unittest.main()
