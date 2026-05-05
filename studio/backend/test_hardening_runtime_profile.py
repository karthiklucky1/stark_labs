import unittest

from app.services.hardening import _resolve_runtime_service_plan


class HardeningRuntimeProfileTests(unittest.TestCase):
    def test_dynamic_nextjs_prefers_detected_runtime_commands(self) -> None:
        profile_name, runtime_name, startup_cmd, install_cmd, probe_path = _resolve_runtime_service_plan(
            profile_type="dynamic_profile",
            blueprint_json={
                "tech_stack": "Next.js 14",
                "startup_command": "npm run dev",
                "install_command": "npm install",
            },
            files={
                "package.json": '{"dependencies":{"next":"14.2.16"}}',
                "next.config.js": "module.exports = {};",
                "src/app/page.tsx": "export default function Page() { return null; }",
            },
        )

        self.assertEqual(profile_name, "dynamic_profile")
        self.assertEqual(runtime_name, "nextjs_webapp")
        self.assertEqual(startup_cmd, "npm run dev -- --hostname 0.0.0.0 --port 3000")
        self.assertIn("NODE_OPTIONS=--max-old-space-size=768", install_cmd)
        self.assertEqual(probe_path, "/")

    def test_dynamic_profile_falls_back_to_blueprint_when_detection_fails(self) -> None:
        profile_name, runtime_name, startup_cmd, install_cmd, probe_path = _resolve_runtime_service_plan(
            profile_type="dynamic_profile",
            blueprint_json={
                "tech_stack": "Custom service",
                "startup_command": "python app.py",
                "install_command": "pip install -r requirements.txt",
            },
            files={"README.md": "No framework markers here."},
        )

        self.assertEqual(profile_name, "dynamic_profile")
        self.assertEqual(runtime_name, "dynamic_profile")
        self.assertEqual(startup_cmd, "python app.py")
        self.assertEqual(install_cmd, "pip install -r requirements.txt")
        self.assertEqual(probe_path, "/")


if __name__ == "__main__":
    unittest.main()
