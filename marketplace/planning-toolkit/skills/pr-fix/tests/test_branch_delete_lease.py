"""Integration proof that branch cleanup refuses a moved remote ref."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

GIT = shutil.which("git")


@unittest.skipUnless(GIT, "git is required")
class BranchDeleteLeaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "pr-fix-test",
            "GIT_AUTHOR_EMAIL": "pr-fix@example.invalid",
            "GIT_COMMITTER_NAME": "pr-fix-test",
            "GIT_COMMITTER_EMAIL": "pr-fix@example.invalid",
        }

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def git(
        self, cwd: Path, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [GIT, *args],
            cwd=cwd,
            env=self.env,
            check=check,
            text=True,
            capture_output=True,
        )

    def test_expected_sha_lease_rejects_branch_that_moved_after_confirmation(self) -> None:
        remote = self.root / "remote.git"
        seed = self.root / "seed"
        lease_repo = self.root / "lease.git"
        remote.mkdir()
        seed.mkdir()
        lease_repo.mkdir()
        self.git(remote, "init", "--bare")
        self.git(seed, "init")
        self.git(seed, "config", "commit.gpgsign", "false")
        (seed / "README.md").write_text("base\n", encoding="utf-8")
        self.git(seed, "add", "README.md")
        self.git(seed, "commit", "-m", "base")
        self.git(seed, "remote", "add", "origin", str(remote))
        self.git(seed, "switch", "-c", "feature")
        (seed / "feature.txt").write_text("confirmed\n", encoding="utf-8")
        self.git(seed, "add", "feature.txt")
        self.git(seed, "commit", "-m", "confirmed feature")
        self.git(seed, "push", "origin", "HEAD:refs/heads/feature")
        expected_sha = self.git(seed, "rev-parse", "HEAD").stdout.strip()

        self.git(lease_repo, "init", "--bare")
        self.git(lease_repo, "remote", "add", "origin", str(remote))

        (seed / "feature.txt").write_text("moved\n", encoding="utf-8")
        self.git(seed, "add", "feature.txt")
        self.git(seed, "commit", "-m", "move feature")
        self.git(seed, "push", "origin", "HEAD:refs/heads/feature")
        moved_sha = self.git(seed, "rev-parse", "HEAD").stdout.strip()

        rejected = self.git(
            lease_repo,
            "push",
            f"--force-with-lease=refs/heads/feature:{expected_sha}",
            "origin",
            ":refs/heads/feature",
            check=False,
        )
        self.assertNotEqual(rejected.returncode, 0)
        live_after_rejection = self.git(
            lease_repo, "ls-remote", "origin", "refs/heads/feature"
        ).stdout.split()[0]
        self.assertEqual(live_after_rejection, moved_sha)

        accepted = self.git(
            lease_repo,
            "push",
            f"--force-with-lease=refs/heads/feature:{moved_sha}",
            "origin",
            ":refs/heads/feature",
            check=False,
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(
            self.git(
                lease_repo,
                "ls-remote",
                "--exit-code",
                "origin",
                "refs/heads/feature",
                check=False,
            ).returncode,
            2,
        )


if __name__ == "__main__":
    unittest.main()
