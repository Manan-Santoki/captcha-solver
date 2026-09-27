import asyncio
import base64
import io
import json
import unittest
import urllib.error
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image
from common.vision import LocalFirstClassifier, OpenRouterVision, VisionError, _NoRedirect, vision_pool
from recaptcha import image_solve, solve


def response(content):
    result = MagicMock()
    result.__enter__.return_value.read.return_value = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
    return result


class VisionTests(unittest.TestCase):
    def setUp(self):
        self.client = OpenRouterVision(key="fixture-api-key", model="mistralai/mistral-medium-3-5", timeout=20)

    def test_one_grid_request_has_correct_model_image_and_bounded_timeout(self):
        with patch("common.vision.urllib.request.build_opener") as factory:
            factory.return_value.open.return_value = response("[8, 0, 0]")
            self.assertEqual(self.client.classify_grid("fixture-png", "red square", 3), [0, 8])
            factory.return_value.open.assert_called_once()
            request = factory.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, "https://openrouter.ai/api/v1/chat/completions")
            payload = json.loads(request.data)
            self.assertEqual(payload["model"], "mistralai/mistral-medium-3-5")
            self.assertEqual(payload["messages"][0]["content"][1]["image_url"], {"url": "data:image/png;base64,fixture-png"})
            self.assertFalse(payload["reasoning"]["enabled"])
            self.assertEqual(factory.return_value.open.call_args.kwargs["timeout"], 20)

    def test_invalid_selections_never_become_no_match_or_click_coordinates(self):
        for value in ['[-1]', '[9]', '[true]', '["2"]', '{}', 'not json']:
            with self.subTest(value=value), patch.object(self.client, "_call", return_value=value):
                with self.assertRaises(VisionError):
                    self.client.classify_grid("image", "bus", 3)

    def test_empty_selection_and_fenced_json_are_valid(self):
        for text, expected in [('[]', []), ('```json\n[1, 3]\n```', [1, 3])]:
            with patch.object(self.client, "_call", return_value=text):
                self.assertEqual(self.client.classify_grid("image", "bus", 3), expected)

    def test_http_failure_is_sanitized_and_not_treated_as_a_negative_classification(self):
        with patch("common.vision.urllib.request.build_opener") as factory:
            factory.return_value.open.side_effect = urllib.error.HTTPError("private-url", 429, "private-body", {}, None)
            with self.assertRaisesRegex(VisionError, "^OpenRouter returned HTTP 429$"):
                self.client.classify("image", "bus")

    def test_transport_failure_hides_request_details(self):
        with patch("common.vision.urllib.request.build_opener") as factory:
            factory.return_value.open.side_effect = RuntimeError("fixture-api-key must not escape")
            with self.assertRaisesRegex(VisionError, "^OpenRouter vision request failed$"):
                self.client.ask("image", "task")

    def test_redirects_are_not_followed_with_authorization(self):
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "", {}, "https://unrelated.example"))

    def test_batch_models_and_unbounded_timeouts_are_rejected(self):
        for model in ["mistralai/mistral-medium-3-5:batch", "mistralai/mistral-medium-3-5-batch"]:
            with self.assertRaises(ValueError):
                OpenRouterVision(key="fixture", model=model)
        for timeout in [0, 41, float('nan')]:
            with self.assertRaises(ValueError):
                OpenRouterVision(key="fixture", timeout=timeout)

    def test_provider_selection_keeps_credentials_on_the_matching_provider(self):
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "fixture-router-key"}), patch("common.vision.KeyPool") as legacy:
            self.assertIsInstance(vision_pool("HCAPTCHA", "missing-keyfile"), OpenRouterVision)
            legacy.assert_not_called()
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": ""}), patch("common.vision.KeyPool") as legacy:
            vision_pool("HCAPTCHA", "legacy-keyfile")
            legacy.assert_called_once()

    def test_attempt_state_is_per_solve_and_yolo_never_uses_remote(self):
        local, remote = object(), object()
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "fixture-router-key"}), patch("recaptcha.onnx_classifier.get_classifier", return_value=local), patch.object(solve, "_build_keypool", return_value=remote):
            first, second = solve._get_keypool("auto"), solve._get_keypool("auto")
            self.assertIs(first.next_attempt(), local)
            self.assertIs(first.next_attempt(), remote)
            self.assertIs(first.next_attempt(), remote)
            self.assertIs(second.next_attempt(), local)
            self.assertIs(solve._get_keypool("yolo"), local)
            self.assertIs(solve._get_keypool("mistral"), remote)

    def test_missing_local_model_uses_remote_immediately(self):
        remote = object()
        self.assertIs(LocalFirstClassifier(None, remote).next_attempt(), remote)

    def test_broken_local_model_falls_back_but_yolo_remains_local(self):
        remote = object()
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "fixture-router-key"}), patch("recaptcha.onnx_classifier.get_classifier", side_effect=RuntimeError("unloadable model")) as local, patch.object(solve, "_build_keypool", return_value=remote):
            self.assertIs(solve._get_keypool("auto").next_attempt(), remote)
            with self.assertRaises(RuntimeError):
                solve._get_keypool("yolo")
            local.reset_mock()
            self.assertIs(solve._get_keypool("mistral"), remote)
            local.assert_not_called()


class ImageTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_failed_local_attempt_switches_to_remote(self):
        local, remote = object(), object()
        plan = LocalFirstClassifier(local, remote)
        with patch.object(solve, "solve_image_challenge", new=AsyncMock(side_effect=[RuntimeError("local failed"), True])) as attempt:
            with self.assertRaises(RuntimeError):
                await solve._solve_image_attempt("page", plan)
            await solve._solve_image_attempt("page", plan)
            self.assertEqual([call.args[1] for call in attempt.await_args_list], [local, remote])

    async def test_whole_grid_uses_one_request_and_valid_page_crop_fallback(self):
        output = io.BytesIO(); Image.new("RGB", (90, 90), "red").save(output, "PNG")
        frame, table, client = MagicMock(), MagicMock(), MagicMock()
        frame.query_selector = AsyncMock(return_value=table)
        frame.page.bring_to_front = AsyncMock()
        table.wait_for_element_state = AsyncMock()
        table.screenshot = AsyncMock(side_effect=asyncio.TimeoutError())
        table.bounding_box = AsyncMock(return_value={"x": 1, "y": 2, "width": 90, "height": 90})
        frame.page.screenshot = AsyncMock(return_value=output.getvalue())
        client.classify_grid.return_value = [1, 3]
        self.assertEqual(await image_solve._classify_grid(frame, client, "bus", 3), [1, 3])
        client.classify_grid.assert_called_once()
        client.classify.assert_not_called()
        frame.page.screenshot.assert_awaited_once()
        self.assertEqual(base64.b64decode(client.classify_grid.call_args.args[0]), output.getvalue())

    async def test_capture_failure_is_not_an_empty_answer(self):
        frame, table = MagicMock(), MagicMock()
        frame.query_selector = AsyncMock(return_value=table)
        frame.page.bring_to_front = AsyncMock()
        table.wait_for_element_state = AsyncMock()
        table.screenshot = AsyncMock(side_effect=asyncio.TimeoutError())
        table.bounding_box = AsyncMock(return_value=None)
        with self.assertRaisesRegex(RuntimeError, "capture failed"):
            await image_solve._classify_grid(frame, MagicMock(), "bus", 3)

    async def test_hidden_challenge_frames_are_skipped(self):
        hidden, visible = MagicMock(), MagicMock()
        hidden.url = visible.url = "https://www.google.com/recaptcha/api2/bframe"
        hidden.locator.return_value.is_visible = AsyncMock(return_value=False)
        visible.locator.return_value.is_visible = AsyncMock(return_value=True)
        self.assertIs(await image_solve._find_bframe(MagicMock(frames=[hidden, visible])), visible)


if __name__ == '__main__':
    unittest.main()
