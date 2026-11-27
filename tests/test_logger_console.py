import errno
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


class SwitchableOutput(io.StringIO):
    error = None

    def fileno(self):
        # Rich only uses its legacy Windows renderer on stdout/stderr descriptors.
        return sys.__stdout__.fileno()

    def flush(self):
        if self.error:
            raise self.error
        super().flush()


class ConsoleOutputTest(unittest.TestCase):
    def test_log_destinations(self):
        # Import in a child: the OAS logger changes cwd and opens its log at import.
        source = Path(__file__).resolve().parents[1] / "module" / "logger.py"
        with tempfile.TemporaryDirectory() as root:
            module_dir = Path(root) / "module"
            module_dir.mkdir()
            (module_dir / "__init__.py").touch()
            shutil.copyfile(source, module_dir / "logger.py")
            subprocess.run([sys.executable, "-B", __file__, "--probe", root], check=True)

    def run_probe(self, root):
        sys.path.insert(0, root)
        from module.logger import console_hdlr, logger

        messages = []
        logger.set_func_logger(messages.append)
        terminal = SwitchableOutput()
        with patch.object(sys, "stdout", terminal):
            logger.info("healthy-info")
            logger.rule("healthy-rule")
            self.assertIn("healthy-info", terminal.getvalue())
            self.assertIn("healthy-rule", terminal.getvalue())

            if os.name == "nt":
                from rich import _windows_renderer

                console_hdlr.console.legacy_windows = True
                with patch.object(_windows_renderer, "legacy_windows_render",
                                  wraps=_windows_renderer.legacy_windows_render) as render:
                    terminal.error = OSError(errno.EINVAL, "invalid console handle")
                    logger.rule("detached-rule")
                    logger.info("detached-info")
                    self.assertTrue(render.called)
                terminal.error = None
                for token in ("detached-rule", "detached-info"):
                    self.assertEqual(Path(logger.log_file).read_text(encoding="utf8").count(token), 1)
                    self.assertEqual("".join(messages).count(token), 1)
                logger.rule("recovered-rule")
                self.assertEqual(terminal.getvalue().count("recovered-rule"), 1)

            class BrokenRenderable:
                def __rich_console__(self, console, options):
                    raise OSError(errno.EINVAL, "render failure")

            with self.assertRaisesRegex(OSError, "render failure"):
                console_hdlr.console.print(BrokenRenderable())
            terminal.error = PermissionError(errno.EACCES, "unrelated failure")
            with self.assertRaisesRegex(PermissionError, "unrelated failure"):
                logger.rule("permission error")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--probe"]:
        ConsoleOutputTest().run_probe(sys.argv[2])
    else:
        unittest.main()
