import os
import sys
import unittest
from unittest.mock import MagicMock, patch

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_dir = os.path.join(root_dir, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from video_rpa.core.hitl_controller import HitlInterventionController


class TestHitlInterventionController(unittest.TestCase):
    def setUp(self):
        HitlInterventionController.reset_instance()

    def tearDown(self):
        HitlInterventionController.reset_instance()

    def test_singleton_instance(self):
        inst1 = HitlInterventionController.get_instance()
        inst2 = HitlInterventionController.get_instance()
        self.assertIs(inst1, inst2)

    def test_intervention_trigger_and_consume(self):
        controller = HitlInterventionController.get_instance()
        self.assertFalse(controller.is_intervention_requested())

        test_instruction = "發現畫面已跳出發布視窗，請點擊關閉按鈕"
        controller.trigger_agent_exploration(test_instruction)
        self.assertTrue(controller.is_intervention_requested())

        consumed = controller.consume_intervention()
        self.assertEqual(consumed, test_instruction)
        self.assertFalse(controller.is_intervention_requested())

    def test_skip_trigger_and_consume(self):
        controller = HitlInterventionController.get_instance()
        self.assertFalse(controller.is_skip_requested())

        controller.trigger_skip()
        self.assertTrue(controller.is_skip_requested())

        self.assertTrue(controller.consume_skip())
        self.assertFalse(controller.is_skip_requested())
        self.assertFalse(controller.consume_skip())

    def test_update_status(self):
        controller = HitlInterventionController.get_instance()
        controller.update_status("正在進行影片標題輸入")
        self.assertEqual(controller._current_step_name, "正在進行影片標題輸入")
        cmd, arg = controller._command_queue.get_nowait()
        self.assertEqual(cmd, "update_status")
        self.assertEqual(arg, "正在進行影片標題輸入")

    def test_close_lifecycle(self):
        controller = HitlInterventionController.get_instance()
        controller.trigger_agent_exploration("測試指示")
        controller.trigger_skip()
        controller.close()

        self.assertFalse(controller.is_intervention_requested())
        self.assertFalse(controller.is_skip_requested())
        cmd, _ = controller._command_queue.get_nowait()
        self.assertEqual(cmd, "close")


if __name__ == "__main__":
    unittest.main()
