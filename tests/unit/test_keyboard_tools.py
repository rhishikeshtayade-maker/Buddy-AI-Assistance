"""Unit tests for BUDDY Controlled Keyboard Tools."""

from __future__ import annotations

import unittest

from app.security.interaction_policy import InteractionPolicy, InteractionSecurityError
from app.tools.keyboard import (
    KeyPressTool,
    MockKeyboardController,
    TypeTextTool,
)


class TestKeyboardTools(unittest.IsolatedAsyncioTestCase):
    """Test keyboard.key_press and keyboard.type_text tools."""

    async def asyncSetUp(self) -> None:
        self.policy = InteractionPolicy()
        self.kbd_ctrl = MockKeyboardController()
        self.key_tool = KeyPressTool(self.policy, self.kbd_ctrl)
        self.type_tool = TypeTextTool(self.policy, self.kbd_ctrl)

    async def test_key_press_execution(self) -> None:
        validated = await self.key_tool.validate_input({"key": "enter"})
        self.assertEqual(validated["key"], "ENTER")

        res = await self.key_tool.execute(validated)
        self.assertTrue(res["pressed"])
        self.assertEqual(res["key"], "ENTER")
        self.assertTrue(await self.key_tool.verify(validated, res))

        self.assertEqual(self.kbd_ctrl.pressed_keys, ["ENTER"])

    async def test_key_press_rejects_unapproved_key(self) -> None:
        with self.assertRaises(InteractionSecurityError):
            await self.key_tool.validate_input({"key": "F13"})

    async def test_type_text_normal_execution_and_privacy(self) -> None:
        validated = await self.type_tool.validate_input({"text": "Hello World!"})
        self.assertEqual(validated["text"], "Hello World!")

        res = await self.type_tool.execute(validated)
        self.assertTrue(res["typed"])
        self.assertEqual(res["character_count"], 12)

        # Critical privacy rule: Output must NOT leak typed text string
        self.assertNotIn("text", res)

        self.assertTrue(await self.type_tool.verify(validated, res))
        self.assertEqual(self.kbd_ctrl.typed_strings, ["Hello World!"])

    async def test_type_text_rejects_sensitive_credentials(self) -> None:
        with self.assertRaises(InteractionSecurityError) as ctx:
            await self.type_tool.validate_input({"text": "My secret password is 1234"})
        self.assertIn("passwords, credentials", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
