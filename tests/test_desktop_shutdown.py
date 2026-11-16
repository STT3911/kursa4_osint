"""Exercise actual desktop lifecycle methods without importing ML/GUI integrations."""
from __future__ import annotations

import ast
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock


def lifecycle_namespace():
    # Compile only the actual lifecycle code so these tests need no display or Telethon.
    source = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8"))
    desktop = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == "OSINTApp")
    methods = [node for node in desktop.body if isinstance(node, ast.FunctionDef)
               and node.name in {"_on_close", "report_callback_exception"}]
    main = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    fake_class = ast.ClassDef(name="OSINTApp", bases=[ast.Name(id="ToolkitBase", ctx=ast.Load())],
                             keywords=[], body=methods, decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[fake_class, main], type_ignores=[]))

    class ToolkitBase:
        def report_callback_exception(self, exc_type, exc_value, traceback):
            self.forwarded(exc_type, exc_value, traceback)

    namespace = {"ToolkitBase": ToolkitBase}
    exec(compile(module, "app.py:lifecycle", "exec"), namespace)
    return namespace


class DesktopShutdownTests(unittest.TestCase):
    def setUp(self):
        self.ns = lifecycle_namespace()
        self.app = self.ns["OSINTApp"]()
        self.app.shutdown_event = threading.Event()
        self.app.sherlock_queue = Mock()
        self.app.snoop_queue = Mock()
        self.app.maigret_queue = Mock()
        self.app.destroy = Mock()
        self.app.forwarded = Mock()

    def test_close_is_idempotent_and_signals_workers(self):
        self.app._on_close()
        self.app._on_close()
        self.assertTrue(self.app.shutdown_event.is_set())
        self.app.destroy.assert_called_once()
        for queue in (self.app.sherlock_queue, self.app.snoop_queue, self.app.maigret_queue):
            queue.put.assert_called_once_with(None)

    def test_interrupt_during_callback_closes_without_error_report(self):
        self.app.report_callback_exception(KeyboardInterrupt, KeyboardInterrupt(), None)
        self.app.destroy.assert_called_once()
        self.app.forwarded.assert_not_called()

    def test_real_callback_errors_are_not_hidden(self):
        error = RuntimeError("real callback failure")
        self.app.report_callback_exception(RuntimeError, error, None)
        self.app.forwarded.assert_called_once_with(RuntimeError, error, None)
        self.app.destroy.assert_not_called()

    def test_interrupt_during_mainloop_closes_and_returns_130(self):
        self.app.mainloop = Mock(side_effect=KeyboardInterrupt)
        self.ns["OSINTApp"] = Mock(return_value=self.app)
        self.assertEqual(self.ns["main"](), 130)
        self.app.destroy.assert_called_once()

    def test_normal_mainloop_returns_success(self):
        self.app.mainloop = Mock()
        self.ns["OSINTApp"] = Mock(return_value=self.app)
        self.assertEqual(self.ns["main"](), 0)

    def test_real_mainloop_errors_propagate(self):
        self.app.mainloop = Mock(side_effect=RuntimeError("real failure"))
        self.ns["OSINTApp"] = Mock(return_value=self.app)
        with self.assertRaisesRegex(RuntimeError, "real failure"):
            self.ns["main"]()


if __name__ == "__main__":
    unittest.main()
