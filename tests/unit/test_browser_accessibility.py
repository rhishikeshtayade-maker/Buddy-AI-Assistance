"""Unit tests for Accessibility tree inspection and node parsing."""

import unittest

from app.browser.accessibility import (
    AccessibilityNode,
    flatten_interactive_nodes,
    parse_accessibility_tree,
)


class TestBrowserAccessibility(unittest.TestCase):
    def test_parse_accessibility_tree(self):
        raw_snapshot = {
            "role": "WebArea",
            "name": "Main Document",
            "children": [
                {
                    "role": "button",
                    "name": "Submit Form",
                    "disabled": False,
                    "children": [],
                },
                {
                    "role": "textbox",
                    "name": "User Name",
                    "value": "Alice",
                    "children": [],
                },
            ],
        }

        tree, count = parse_accessibility_tree(raw_snapshot, max_nodes=10)
        self.assertIsNotNone(tree)
        self.assertEqual(tree.role, "WebArea")
        self.assertEqual(len(tree.children), 2)
        self.assertEqual(tree.children[0].role, "button")
        self.assertEqual(tree.children[0].name, "Submit Form")
        self.assertEqual(count, 3)

    def test_bounded_node_count(self):
        # Create a deep/wide tree
        raw = {
            "role": "div",
            "children": [{"role": "span", "name": f"child_{i}", "children": []} for i in range(50)],
        }
        tree, count = parse_accessibility_tree(raw, max_nodes=5)
        self.assertLessEqual(count, 5)
        self.assertLessEqual(len(tree.children), 4)

    def test_flatten_interactive_nodes(self):
        tree = AccessibilityNode(
            role="WebArea",
            name="Doc",
            children=[
                AccessibilityNode(role="generic", name="container", children=[
                    AccessibilityNode(role="button", name="Click Me"),
                    AccessibilityNode(role="textbox", name="Search", value="test"),
                ]),
                AccessibilityNode(role="link", name="Home Page"),
                AccessibilityNode(role="paragraph", name="Static paragraph"),
            ],
        )

        interactive = flatten_interactive_nodes(tree)
        roles = [n.role for n in interactive]
        self.assertIn("button", roles)
        self.assertIn("textbox", roles)
        self.assertIn("link", roles)
        self.assertNotIn("paragraph", roles)
        self.assertNotIn("generic", roles)


if __name__ == "__main__":
    unittest.main()
