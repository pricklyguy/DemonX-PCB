from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "phase2g" / "run_pcbprep.ps1"


@unittest.skipUnless(os.name == "nt", "PowerShell launcher is Windows-only")
class PowerShellLauncherTests(unittest.TestCase):
    def test_actual_launcher_opens_window_from_root_and_spaced_unrelated_cwd(self):
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        self.assertIsNotNone(powershell, "PowerShell is required for the launcher smoke test")
        with tempfile.TemporaryDirectory(prefix="phase2m launcher spaces ") as temp:
            temp_root = Path(temp)
            extension_path = temp_root / "existing PYTHONPATH entry with spaces"
            extension_path.mkdir()
            outside_cwd = temp_root / "unrelated working directory with spaces"
            outside_cwd.mkdir()
            marker = temp_root / "sitecustomize ran.txt"
            (extension_path / "sitecustomize.py").write_text(
                "from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('loaded')\n",
                encoding="utf-8")
            env = os.environ.copy()
            env["QT_QPA_PLATFORM"] = "offscreen"
            original_pythonpath = str(extension_path)
            env["PYTHONPATH"] = original_pythonpath
            command = [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                       "-File", str(LAUNCHER), "--smoke-test-startup"]
            cases = [(ROOT, env, True), (outside_cwd, env, True)]
            clean_env = env.copy()
            clean_env.pop("PYTHONPATH", None)
            cases.append((outside_cwd, clean_env, False))
            for cwd, child_env, expect_pythonpath_entry in cases:
                marker.unlink(missing_ok=True)
                completed = subprocess.run(command, cwd=cwd, env=child_env, capture_output=True,
                                           text=True, encoding="utf-8", errors="replace", timeout=45)
                self.assertEqual(completed.returncode, 0,
                                 f"launcher failed from {cwd}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}")
                self.assertIn("PCB_PREP_STARTUP_OK", completed.stdout)
                self.assertEqual(marker.is_file(), expect_pythonpath_entry,
                                 "existing PYTHONPATH entry was discarded or unexpected path customization ran")
                self.assertEqual(child_env.get("PYTHONPATH"), original_pythonpath if expect_pythonpath_entry else None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
