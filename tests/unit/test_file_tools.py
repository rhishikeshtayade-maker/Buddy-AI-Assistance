"""Unit tests for BUDDY Sandboxed Filesystem Tools."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.security.path_policy import PathPolicy
from app.tools.filesystem import (
    FileCopyTool,
    FileCreateTool,
    FileMoveTool,
    FileReadTool,
    FileRenameTool,
    FileSearchTool,
)


class TestFileTools(unittest.IsolatedAsyncioTestCase):
    """Test filesystem tools within a sandboxed temporary directory."""

    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.sandbox = Path(self.temp_dir.name).resolve()
        self.policy = PathPolicy(allowed_roots=[self.sandbox])

        self.create_tool = FileCreateTool(self.policy)
        self.read_tool = FileReadTool(self.policy)
        self.search_tool = FileSearchTool(self.policy)
        self.rename_tool = FileRenameTool(self.policy)
        self.copy_tool = FileCopyTool(self.policy)
        self.move_tool = FileMoveTool(self.policy)

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_file_create_and_read(self) -> None:
        file_path = self.sandbox / "hello.txt"
        create_args = {
            "path": str(file_path),
            "content": "Hello World from BUDDY!",
        }
        res = await self.create_tool.execute(create_args)
        self.assertTrue(await self.create_tool.verify(create_args, res))

        read_args = {"path": str(file_path)}
        read_res = await self.read_tool.execute(read_args)
        self.assertEqual(read_res["content"], "Hello World from BUDDY!")
        self.assertTrue(await self.read_tool.verify(read_args, read_res))

    async def test_file_create_overwrite_protection(self) -> None:
        file_path = self.sandbox / "existing.txt"
        file_path.write_text("initial", encoding="utf-8")

        # By default overwrite=False, should fail
        with self.assertRaises(FileExistsError):
            await self.create_tool.execute({
                "path": str(file_path),
                "content": "new text",
                "overwrite": False,
            })

    async def test_file_search(self) -> None:
        (self.sandbox / "doc1.txt").write_text("one", encoding="utf-8")
        (self.sandbox / "doc2.txt").write_text("two", encoding="utf-8")
        (self.sandbox / "image.png").write_text("img", encoding="utf-8")

        search_args = {
            "directory": str(self.sandbox),
            "pattern": "*.txt",
        }
        res = await self.search_tool.execute(search_args)
        self.assertEqual(res["count"], 2)
        self.assertTrue(await self.search_tool.verify(search_args, res))

    async def test_file_rename(self) -> None:
        src = self.sandbox / "original.txt"
        dst = self.sandbox / "renamed.txt"
        src.write_text("data", encoding="utf-8")

        args = {"source_path": str(src), "destination_path": str(dst)}
        res = await self.rename_tool.execute(args)
        self.assertTrue(res["renamed"])
        self.assertTrue(await self.rename_tool.verify(args, res))
        self.assertFalse(src.exists())
        self.assertTrue(dst.exists())

    async def test_file_copy(self) -> None:
        src = self.sandbox / "source.txt"
        dst = self.sandbox / "copied.txt"
        src.write_text("copy content", encoding="utf-8")

        args = {"source_path": str(src), "destination_path": str(dst)}
        res = await self.copy_tool.execute(args)
        self.assertTrue(res["copied"])
        self.assertTrue(await self.copy_tool.verify(args, res))
        self.assertTrue(src.exists())
        self.assertTrue(dst.exists())

    async def test_file_move(self) -> None:
        sub = self.sandbox / "target_folder"
        sub.mkdir()
        src = self.sandbox / "tomove.txt"
        dst = sub / "tomove.txt"
        src.write_text("move content", encoding="utf-8")

        args = {"source_path": str(src), "destination_path": str(dst)}
        res = await self.move_tool.execute(args)
        self.assertTrue(res["moved"])
        self.assertTrue(await self.move_tool.verify(args, res))
        self.assertFalse(src.exists())
        self.assertTrue(dst.exists())


if __name__ == "__main__":
    unittest.main()
