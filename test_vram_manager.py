import os
import signal
import subprocess
import unittest

from vram_manager import (
    Process,
    IdleTracker,
    decorate,
    identity,
    parse_activity,
    parse_snapshot,
    process_activity,
    terminate,
)


class AlertBudgetTests(unittest.TestCase):
    def test_cooldown_survives_restart_and_clock_rollback(self):
        import tempfile
        from pathlib import Path
        from backend import AlertBudget, Settings

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            budget = AlertBudget(Settings(path))
            self.assertFalse(budget.claim(10000, False))
            self.assertTrue(budget.claim(10000, True))
            restarted = AlertBudget(Settings(path))
            self.assertFalse(restarted.claim(10001, True))
            self.assertFalse(restarted.claim(9000, True))
            self.assertTrue(restarted.claim(13600, True))

    def test_failed_persistence_suppresses_banner(self):
        from backend import AlertBudget, Settings
        from unittest.mock import patch

        settings = Settings("/tmp/unused-vram-test-settings")
        with patch.object(settings, "save", return_value=False):
            self.assertFalse(AlertBudget(settings).claim(10000, True))


class ManagerTests(unittest.TestCase):
    def test_graphics_compute_multi_gpu_and_unknown(self):
        xml = """<nvidia_smi_log><gpu><product_name>GPU</product_name>
        <fb_memory_usage><used>400 MiB</used><total>1000 MiB</total></fb_memory_usage>
        <processes>
        <process_info><pid>10</pid><type>G</type><used_memory>100 MiB</used_memory></process_info>
        <process_info><pid>11</pid><type>C</type><used_memory>200 MiB</used_memory></process_info>
        <process_info><pid>12</pid><type>G</type><used_memory>N/A</used_memory></process_info>
        </processes></gpu><gpu><processes>
        <process_info><pid>10</pid><type>G</type><used_memory>50 MiB</used_memory></process_info>
        </processes></gpu></nvidia_smi_log>"""
        gpus, processes, unknown = parse_snapshot(xml)
        self.assertEqual(len(gpus), 2)
        self.assertEqual(unknown, 1)
        self.assertEqual([(p.pid, p.memory) for p in processes], [(10, 150), (11, 200)])
        self.assertEqual(processes[0].gpu, "GPU (0), GPU (1)")

    def test_listed_dashes_are_quiet_and_unlisted_is_unknown(self):
        readings = parse_activity(
            "0 10 C - - - - - - python\n0 11 C 0 0 - - - - python\n0 12 G 0 0 20 - - - video"
        )
        self.assertEqual(readings[(0, 10)], 0)
        self.assertEqual(readings[(0, 11)], 0)
        self.assertEqual(readings[(0, 12)], 20)
        unlisted = Process(13, "Test", 200, "GPU", "C", gpu_indices=(0,))
        self.assertIsNone(process_activity(unlisted, readings))

    def test_protected_by_reported_name_when_executable_unreadable(self):
        # Another user's display server: /proc details are unreadable (here the PID
        # does not exist at all), but NVIDIA still reports its name.
        p = decorate(Process(2**22 + 7, "/usr/lib/xorg/Xorg", 300, "GPU", "G"))
        self.assertTrue(p.protected)
        with self.assertRaises(RuntimeError):
            terminate(p)

    def test_real_pmon_output_from_an_idle_model_server(self):
        # Captured with `nvidia-smi pmon -c 1 -s u` (driver 580, RTX 5070). The python
        # row is a model server holding 2.9 GiB, untouched for hours.
        output = (
            "# gpu         pid   type     sm    mem    enc    dec    jpg    ofa    command \n"
            "# Idx           #    C/G      %      %      %      %      %      %    name \n"
            "    0       4271     G      -      -      -      -      -      -    Xorg           \n"
            "    0       4474     G      2      0      -      -      -      -    gnome-shell    \n"
            "    0    1214741     G      -      -      -      -      -      -    nautilus       \n"
            "    0    3955346     C      -      -      -      -      -      -    python         \n"
        )
        readings = parse_activity(output)
        self.assertEqual(readings[(0, 4474)], 2)
        self.assertEqual(readings[(0, 3955346)], 0)
        server = Process(3955346, "Python", 2908, "GPU", "C", started="s", gpu_indices=(0,))
        server.activity = process_activity(server, readings)
        server.cpu_percent = 1.2   # background threads of an idle server
        tracker = IdleTracker()
        for now in range(0, 600, 2):
            self.assertEqual(tracker.update([server], now, minutes=10, minimum=1024), [])
        self.assertEqual(tracker.update([server], 600, minutes=10, minimum=1024), [server])

    def test_idle_alert_once_and_reset(self):
        tracker = IdleTracker()
        p = Process(
            10, "Test", 100, "GPU", "C", started="123", activity=0, cpu_percent=0
        )
        self.assertEqual(tracker.update([p], 0, minutes=1), [])
        for now in range(10, 60, 10):
            self.assertEqual(tracker.update([p], now, minutes=1), [])
        self.assertEqual(tracker.update([p], 60, minutes=1), [p])
        self.assertEqual(tracker.update([p], 70, minutes=1), [])
        p.activity = None
        tracker.update([p], 80, minutes=1)
        self.assertEqual(p.idle_seconds, 0)
        p.activity = 0
        tracker.update([p], 90, minutes=1)
        self.assertEqual(p.idle_seconds, 0)
        tracker.update([p], 120, minutes=1)
        self.assertEqual(p.idle_seconds, 0)
        p.started = "replacement"
        tracker.update([p], 130, minutes=1)
        self.assertEqual(p.idle_seconds, 0)

    def test_quit_and_force_quit_disposable_processes(self):
        for force in (False, True):
            child = subprocess.Popen(["sleep", "60"])
            try:
                p = decorate(Process(child.pid, "sleep", 100, "0", "C"))
                terminate(p, force)
                self.assertEqual(
                    child.wait(timeout=3), -signal.SIGKILL if force else -signal.SIGTERM
                )
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()

    def test_changed_identity_cannot_be_killed(self):
        child = subprocess.Popen(["sleep", "60"])
        try:
            p = decorate(Process(child.pid, "sleep", 100, "0", "C"))
            p.target_started = "wrong-start-time"
            with self.assertRaises(RuntimeError):
                terminate(p)
            self.assertIsNone(child.poll())
        finally:
            child.kill()
            child.wait()


class ReleaseTests(unittest.TestCase):
    def test_partial_multi_gpu_readings_are_unknown(self):
        from backend import process_activity

        p = Process(22, "Test", 200, "Two GPUs", "C", gpu_indices=(0, 1))
        self.assertIsNone(process_activity(p, {(0, 22): 0}))
        self.assertEqual(process_activity(p, {(0, 22): 0, (1, 22): 0}), 0)
        self.assertEqual(process_activity(p, {(0, 22): 20}), 20)

    def test_activity_headers_and_command_arguments(self):
        output = "# gpu pid type sm mem enc dec command\n0 2 C 0 0 - - python 99\n"
        self.assertEqual(parse_activity(output)[(0, 2)], 0)
        output = (
            "# gpu pid type sm mem enc dec jpg ofa command\n0 2 G - - 15 - - - video\n"
        )
        self.assertEqual(parse_activity(output)[(0, 2)], 15)

    def test_settings_round_trip_and_validation(self):
        import tempfile
        from pathlib import Path
        from backend import Settings

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config" / "settings.json"
            settings = Settings(path)
            settings.values.update(
                minimum=512, idle_minutes=4, alerts=False, ignored=["app"]
            )
            self.assertTrue(settings.save())
            self.assertEqual(Settings(path).values, settings.values)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            path.write_text(
                '{"minimum": -100, "idle_minutes": 10000, "alerts": "false", "ignored": [1, "app"]}'
            )
            values = Settings(path).values
            self.assertEqual(values["minimum"], 0)
            self.assertEqual(values["idle_minutes"], 120)
            self.assertFalse(values["alerts"])
            self.assertEqual(values["ignored"], ["app"])
            path.write_text("broken json")
            self.assertTrue(Settings(path).error)

    def test_muted_snoozed_and_protected_do_not_notify(self):
        p = Process(2, "Test", 200, "GPU", "C", started="a", activity=0, cpu_percent=0)
        for options in (
            {"ignored": [p.app_key]},
            {"snoozed": {p.app_key: 1000}},
            {"enabled": False},
        ):
            tracker = IdleTracker()
            for now in range(0, 100, 10):
                self.assertEqual(tracker.update([p], now, minutes=1, **options), [])
        p.protected = True
        tracker = IdleTracker()
        for now in range(0, 100, 10):
            self.assertEqual(tracker.update([p], now, minutes=1), [])
        with self.assertRaisesRegex(RuntimeError, "protected"):
            terminate(p)

    def test_busy_and_below_threshold_reset_idle(self):
        p = Process(2, "Test", 200, "GPU", "C", started="a", activity=0, cpu_percent=0)
        tracker = IdleTracker()
        tracker.update([p], 0)
        tracker.update([p], 10)
        self.assertEqual(p.idle_seconds, 10)
        p.activity = 1
        tracker.update([p], 20)
        self.assertEqual(p.idle_seconds, 0)
        p.activity = 0
        p.memory = 99
        tracker.update([p], 30)
        self.assertEqual(tracker.states, {})

    def test_quit_watch_success_restart_and_timeout(self):
        from backend import QuitWatch
        from unittest.mock import patch

        p = Process(
            2, "Test", 200, "GPU", "C", started="a", target_pid=2, target_started="a"
        )
        watch = QuitWatch(p, 1000, 0, {p.key})
        with patch("backend.identity", return_value=("a", 1)):
            self.assertFalse(watch.check([p], 1000, 1)[1])
            self.assertIn("Still running", watch.check([p], 1000, 11)[0])
        with patch("backend.identity", side_effect=ProcessLookupError):
            message, done = watch.check([], 750, 12)
            self.assertIn("increased by 250 MiB overall", message)
            self.assertFalse(done)
            replacement = Process(3, "Test", 200, "GPU", "C", started="b")
            self.assertIn("possibly restarted", watch.check([replacement], 950, 13)[0])

    def test_nonfinite_memory_is_unknown(self):
        from backend import amount

        self.assertIsNone(amount("nan MiB"))
        self.assertIsNone(amount("-1 MiB"))
        self.assertEqual(amount("0 MiB"), 0)


class ContextTests(unittest.TestCase):
    def test_login_startup_enable_disable(self):
        import tempfile
        from unittest.mock import patch
        import autostart

        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": folder}):
                autostart.set_enabled(True, ["/tmp/example app/vram-manager"])
                self.assertTrue(autostart.enabled())
                self.assertIn(
                    'Exec="/tmp/example app/vram-manager"', autostart.path().read_text()
                )
                autostart.set_enabled(False)
                self.assertFalse(autostart.enabled())

    def test_configurable_alert_memory_threshold(self):
        tracker = IdleTracker()
        p = Process(
            4, "Test", 512, "GPU", "C", started="start", activity=0, cpu_percent=0
        )
        for now in range(0, 80, 10):
            self.assertEqual(tracker.update([p], now, minutes=1, minimum=1024), [])
        p.memory = 1024
        for now in range(80, 140, 10):
            self.assertEqual(tracker.update([p], now, minutes=1, minimum=1024), [])
        self.assertEqual(tracker.update([p], 140, minutes=1, minimum=1024), [p])

    def test_cpu_interval_ram_and_pid_reuse(self):
        from backend import ResourceTracker

        reading = ["start", 100, 256]
        tracker = ResourceTracker(lambda pid: tuple(reading), ticks_per_second=100)
        p = Process(4, "Test", 200, "GPU", "C", started="start")
        tracker.update([p], 10)
        self.assertIsNone(p.cpu_percent)
        self.assertEqual(p.ram_mib, 256)
        reading[1] = 400
        tracker.update([p], 12)
        self.assertEqual(p.cpu_percent, 150)
        reading[0] = "replacement"
        tracker.update([p], 14)
        self.assertIsNone(p.cpu_percent)
        self.assertIsNone(p.ram_mib)
        self.assertEqual(tracker.previous, {})

    def test_cpu_missing_busy_and_gap_suppress_idle(self):
        p = Process(4, "Test", 200, "GPU", "C", started="start", activity=0)
        for cpu in (None, 5, 150):
            p.cpu_percent = cpu
            tracker = IdleTracker()
            for now in range(0, 130, 10):
                self.assertEqual(tracker.update([p], now, minutes=1), [])
            self.assertEqual(tracker.states, {})
        p.cpu_percent = 0
        tracker.update([p], 200, minutes=1)
        tracker.update([p], 230, minutes=1)
        self.assertEqual(p.idle_seconds, 0)

    def test_alert_cooldown_survives_activity_reset(self):
        tracker = IdleTracker()
        p = Process(
            4, "Test", 200, "GPU", "C", started="start", activity=0, cpu_percent=0
        )
        for now in range(0, 60, 10):
            tracker.update([p], now, minutes=1)
        self.assertEqual(tracker.update([p], 60, minutes=1), [p])
        p.cpu_percent = 5
        tracker.update([p], 70, minutes=1)
        p.cpu_percent = 0
        for now in range(80, 300, 10):
            self.assertEqual(tracker.update([p], now, minutes=1), [])

    def test_live_cpu_and_ram_for_disposable_worker(self):
        import sys
        import time
        from backend import ResourceTracker

        child = subprocess.Popen([sys.executable, "-c", "while True: pass"])
        try:
            p = decorate(Process(child.pid, "Test worker", 100, "GPU", "C"))
            tracker = ResourceTracker()
            tracker.update([p])
            time.sleep(0.4)
            tracker.update([p])
            self.assertGreater(p.cpu_percent, 0)
            self.assertGreater(p.ram_mib, 0)
        finally:
            child.kill()
            child.wait()


if __name__ == "__main__":
    unittest.main()
