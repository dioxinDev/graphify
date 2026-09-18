from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from graphify.cluster import bidirectional_consensus_relaxation
from graphify.watch import (
    _compute_ast_delta,
    _compute_blast_radius,
    _git_diff_changes,
)


class TestPacreDelta(unittest.TestCase):
    def test_git_diff_changes_null_delimiters(self):
        # Simulated 'git diff -z --name-status' output
        # A file1.py \0 M file2.py \0 D file3.py \0 R100 old.py \0 new.py \0
        fake_stdout = b"A\0file1.py\0M\0file2.py\0D\0file3.py\0R100\0old.py\0new.py\0"
        mock_proc = MagicMock(returncode=0, stdout=fake_stdout, stderr=b"")

        with patch("subprocess.run", return_value=mock_proc):
            res = _git_diff_changes(base="HEAD~1", head="HEAD")

        self.assertEqual(res["added"], ["file1.py"])
        self.assertEqual(res["modified"], ["file2.py"])
        self.assertEqual(res["deleted"], ["file3.py"])
        self.assertEqual(res["renamed"], [{"old": "old.py", "new": "new.py"}])

    def test_git_diff_raises_on_failure(self):
        mock_proc = MagicMock(returncode=128, stdout=b"", stderr=b"fatal: not a git repo")
        with patch("subprocess.run", return_value=mock_proc):
            with self.assertRaises(RuntimeError) as ctx:
                _git_diff_changes(base="HEAD~1", head="HEAD")
            self.assertIn("fatal: not a git repo", str(ctx.exception))

    def test_ast_delta_and_blast_radius(self):
        old_graph = {
            "nodes": [
                {"id": "A", "file": "src/a.py", "community": 1, "community_name": "COMM_A"},
                {"id": "B", "file": "src/b.py", "community": 2, "community_name": "COMM_B"},
            ],
            "edges": [{"source": "A", "target": "B", "relation": "CALLS"}],
        }

        # New graph has C added and calling A, edge A->B removed
        new_graph = {
            "nodes": [
                {"id": "A", "file": "src/a.py", "community": 1, "community_name": "COMM_A"},
                {"id": "B", "file": "src/b.py", "community": 2, "community_name": "COMM_B"},
                {"id": "C", "file": "src/c.py", "community": 1, "community_name": "COMM_A"},
            ],
            "edges": [{"source": "C", "target": "A", "relation": "CALLS"}],
        }

        delta = _compute_ast_delta(old_graph, new_graph)
        self.assertEqual(len(delta["addedSymbols"]), 1)
        self.assertEqual(delta["addedSymbols"][0]["id"], "C")
        self.assertEqual(len(delta["removedEdges"]), 1)
        self.assertEqual(delta["removedEdges"][0]["source"], "A")
        self.assertEqual(delta["removedEdges"][0]["target"], "B")

        # Blast radius on C (should hit A downstream)
        blast = _compute_blast_radius(new_graph, ["C"])
        self.assertIn("A", blast["directDownstream"])
        self.assertIn("COMM_A", blast["impactedSubsystems"])

    def test_bidirectional_consensus_relaxation(self):
        graph = {
            "nodes": [
                {"id": "A1", "file": "src/a.py", "community": 1, "community_name": "COMM_A"},
                {"id": "B1", "file": "src/b.py", "community": 2, "community_name": "COMM_B"},
                {"id": "B2", "file": "src/b.py", "community": 2, "community_name": "COMM_B"},
                {"id": "X", "file": "src/x.py"},
            ],
            "links": [
                {"source": "B1", "target": "B2"},
                {"source": "X", "target": "B1"},
                {"source": "X", "target": "B2"},
            ],
        }

        res_graph, ambiguities = bidirectional_consensus_relaxation(graph, ["src/x.py"])
        x_node = next(n for n in res_graph["nodes"] if n["id"] == "X")
        self.assertEqual(x_node["community"], 2)
        self.assertEqual(x_node["community_name"], "COMM_B")
        self.assertEqual(ambiguities, [])

    def test_cli_diff_requires_git_repo(self):
        from graphify.cli import dispatch_command

        # Test when not a git repository
        with patch.object(sys, "argv", ["graphify", "diff"]):
            with patch("subprocess.run", return_value=MagicMock(returncode=128)):
                with self.assertRaises(SystemExit) as cm:
                    dispatch_command("diff")
                self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
