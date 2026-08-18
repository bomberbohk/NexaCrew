"""
Codex → Claude Code orchestration engine.

Pipeline:
  1. User prompt  -> Codex CLI  (planning / analysis)
  2. Codex output -> Claude Code CLI (implementation)
  3. If programming task: Claude writes a Markdown spec into ./handoff,
     which is then opened in VS Code for Claude Fable 5 (Copilot) to implement.
"""

from __future__ import annotations

import datetime
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

HANDOFF_DIR = Path(__file__).parent / "handoff"

PROGRAMMING_HINTS = re.compile(
    r"\b(code|coding|program|script|function|class|bug|debug|api|app|website|"
    r"frontend|backend|python|javascript|typescript|java\b|c\+\+|c#|rust|go\b|"
    r"sql|html|css|refactor|implement|compile|library|framework|algorithm)\b",
    re.IGNORECASE,
)


@dataclass
class PipelineResult:
    user_prompt: str
    codex_response: str = ""
    claude_response: str = ""
    md_file: Optional[Path] = None
    is_programming: bool = False
    errors: list[str] = field(default_factory=list)


def _find_cli(*names: str) -> Optional[str]:
    """Locate first available executable among names (handles .cmd on Windows)."""
    for name in names:
        path = shutil.which(name)
        if path:
            # On Windows, shutil.which may return an extension-less shell shim
            # (e.g. npm's bash script) that subprocess cannot execute. Prefer
            # a sibling .cmd/.exe/.bat launcher when one exists.
            if os.name == "nt" and not Path(path).suffix:
                for ext in (".cmd", ".exe", ".bat", ".ps1"):
                    alt = shutil.which(name + ext) or (
                        str(Path(path).with_suffix(ext))
                        if Path(path).with_suffix(ext).exists()
                        else None
                    )
                    if alt:
                        return alt
            return path
    return None


def _run(cmd: list[str], input_text: Optional[str] = None, timeout: int = 600) -> tuple[str, str, int]:
    proc = subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    return proc.stdout.strip(), proc.stderr.strip(), proc.returncode


def is_programming_task(prompt: str) -> bool:
    return bool(PROGRAMMING_HINTS.search(prompt))


class Orchestrator:
    def __init__(self) -> None:
        self.codex_cli = _find_cli("codex", "codex.cmd")
        self.claude_cli = _find_cli("claude", "claude.cmd")
        self.code_cli = _find_cli("code", "code.cmd")
        HANDOFF_DIR.mkdir(exist_ok=True)

    # ---------------- Codex stage ----------------
    def ask_codex(self, prompt: str) -> str:
        if not self.codex_cli:
            raise RuntimeError("Codex CLI not found on PATH. Install with: npm i -g @openai/codex")
        full_prompt = (
            "You are the PLANNING agent in a two-agent pipeline. Analyze the user's request "
            "and produce a clear, structured plan/answer that another agent (Claude Code) will "
            "use to implement it. Be specific and actionable.\n\nUser request:\n" + prompt
        )
        out, err, rc = _run([self.codex_cli, "exec", "--skip-git-repo-check", full_prompt])
        if rc != 0 and not out:
            # The banner is at the head of stderr; the actual error is at the tail.
            raise RuntimeError(f"Codex failed (exit {rc}): {err.strip()[-800:]}")
        return out or err

    # ---------------- Claude stage ----------------
    def ask_claude(self, user_prompt: str, codex_plan: str, programming: bool) -> tuple[str, Optional[Path]]:
        if not self.claude_cli:
            raise RuntimeError("Claude Code CLI not found on PATH. Install with: npm i -g @anthropic-ai/claude-code")

        md_file: Optional[Path] = None
        if programming:
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            md_file = HANDOFF_DIR / f"task_{stamp}.md"
            instruction = (
                "You are the IMPLEMENTATION agent. Below is the original user request and a plan "
                "produced by Codex. This is a PROGRAMMING task. Review/refine the plan and write a "
                f"complete implementation specification as a Markdown file at exactly this path: {md_file}\n"
                "The Markdown file must contain: 1) Objective, 2) Architecture, 3) File-by-file "
                "implementation details with code, 4) Setup/run instructions, 5) Acceptance criteria. "
                "It will be handed to VS Code Copilot (Claude Fable 5) to implement. "
                "Create the file, then summarize what you wrote.\n\n"
                f"## Original user request\n{user_prompt}\n\n## Codex plan\n{codex_plan}"
            )
            cmd = [self.claude_cli, "-p", "--permission-mode", "acceptEdits",
                   "--allowedTools", "Write", "Edit", instruction]
        else:
            instruction = (
                "You are the IMPLEMENTATION/refinement agent. Below is the user's request and a plan "
                "from Codex. Produce the final, polished answer for the user.\n\n"
                f"## Original user request\n{user_prompt}\n\n## Codex plan\n{codex_plan}"
            )
            cmd = [self.claude_cli, "-p", instruction]

        out, err, rc = _run(cmd, timeout=900)
        if rc != 0 and not out:
            raise RuntimeError(f"Claude Code failed (exit {rc}): {err[:800]}")

        if md_file and not md_file.exists():
            # Fallback: save Claude's answer as the spec itself.
            md_file.write_text(
                f"# Task Specification\n\n> Auto-saved from Claude Code output\n\n"
                f"## Original request\n{user_prompt}\n\n{out}",
                encoding="utf-8",
            )
        return out or err, md_file

    # ---------------- VS Code handoff ----------------
    def open_in_vscode(self, md_file: Path) -> bool:
        if not self.code_cli:
            return False
        subprocess.Popen(
            [self.code_cli, str(md_file.parent), str(md_file)],
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return True

    # ---------------- Full pipeline ----------------
    def run_pipeline(
        self,
        prompt: str,
        on_stage: Callable[[str, str], None] = lambda stage, status: None,
        open_vscode: bool = True,
    ) -> PipelineResult:
        result = PipelineResult(user_prompt=prompt, is_programming=is_programming_task(prompt))

        on_stage("codex", "running")
        try:
            result.codex_response = self.ask_codex(prompt)
            on_stage("codex", "done")
        except Exception as e:
            result.errors.append(str(e))
            on_stage("codex", "error")
            return result

        on_stage("claude", "running")
        try:
            result.claude_response, result.md_file = self.ask_claude(
                prompt, result.codex_response, result.is_programming
            )
            on_stage("claude", "done")
        except Exception as e:
            result.errors.append(str(e))
            on_stage("claude", "error")
            return result

        if result.is_programming and result.md_file:
            on_stage("vscode", "running")
            ok = self.open_in_vscode(result.md_file) if open_vscode else False
            on_stage("vscode", "done" if ok else "error")
        else:
            on_stage("vscode", "skipped")
        return result
