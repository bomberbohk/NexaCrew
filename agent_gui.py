"""
AI Agent Bridge — professional GUI orchestrating Codex CLI + Claude Code + VS Code.

Run:  python agent_gui.py
"""

from __future__ import annotations

import threading
import tkinter as tk
from datetime import datetime

import customtkinter as ctk

from orchestrator import Orchestrator, PipelineResult

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

ACCENT = "#3b82f6"
BG_CARD = "#1e2430"
FG_MUTED = "#8b95a7"

STAGE_COLORS = {
    "idle": ("#3a4152", "waiting"),
    "running": ("#eab308", "running…"),
    "done": ("#22c55e", "done ✓"),
    "error": ("#ef4444", "error ✗"),
    "skipped": ("#64748b", "skipped"),
}


class StageIndicator(ctk.CTkFrame):
    def __init__(self, master, title: str, icon: str):
        super().__init__(master, fg_color=BG_CARD, corner_radius=12)
        self.dot = ctk.CTkLabel(self, text="●", text_color=STAGE_COLORS["idle"][0],
                                font=("Segoe UI", 18))
        self.dot.pack(side="left", padx=(12, 4), pady=8)
        ctk.CTkLabel(self, text=f"{icon}  {title}", font=("Segoe UI Semibold", 13)).pack(
            side="left", padx=2, pady=8)
        self.status = ctk.CTkLabel(self, text="waiting", text_color=FG_MUTED,
                                   font=("Segoe UI", 11))
        self.status.pack(side="left", padx=(8, 14), pady=8)

    def set_state(self, state: str):
        color, label = STAGE_COLORS.get(state, STAGE_COLORS["idle"])
        self.dot.configure(text_color=color)
        self.status.configure(text=label, text_color=color)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("AI Agent Bridge — Codex ✕ Claude Code ✕ VS Code")
        self.geometry("1100x780")
        self.minsize(900, 640)

        self.orch = Orchestrator()
        self.busy = False

        self._build_header()
        self._build_pipeline_bar()
        self._build_chat()
        self._build_input()
        self._check_environment()

    # ---------- UI construction ----------
    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(16, 4))
        ctk.CTkLabel(header, text="🤖 AI Agent Bridge",
                     font=("Segoe UI Semibold", 24)).pack(side="left")
        ctk.CTkLabel(header,
                     text="Codex plans → Claude Code implements → VS Code (Claude Fable 5) builds",
                     text_color=FG_MUTED, font=("Segoe UI", 12)).pack(side="left", padx=16, pady=(8, 0))
        self.vscode_switch = ctk.CTkSwitch(header, text="Auto-open VS Code", font=("Segoe UI", 12))
        self.vscode_switch.select()
        self.vscode_switch.pack(side="right")

    def _build_pipeline_bar(self):
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=20, pady=8)
        self.stages: dict[str, StageIndicator] = {}
        for key, title, icon in [
            ("codex", "Codex — Planning", "🧠"),
            ("claude", "Claude Code — Implementation", "⚙️"),
            ("vscode", "VS Code — Claude Fable 5", "🚀"),
        ]:
            ind = StageIndicator(bar, title, icon)
            ind.pack(side="left", padx=(0, 10))
            self.stages[key] = ind
            if key != "vscode":
                ctk.CTkLabel(bar, text="→", text_color=FG_MUTED,
                             font=("Segoe UI", 16)).pack(side="left", padx=(0, 10))

    def _build_chat(self):
        self.chat = ctk.CTkTextbox(self, font=("Cascadia Code", 12), wrap="word",
                                   fg_color="#141821", corner_radius=12)
        self.chat.pack(fill="both", expand=True, padx=20, pady=8)
        self.chat.tag_config("user", foreground="#60a5fa")
        self.chat.tag_config("codex", foreground="#34d399")
        self.chat.tag_config("claude", foreground="#f0abfc")
        self.chat.tag_config("system", foreground=FG_MUTED)
        self.chat.tag_config("error", foreground="#f87171")
        self.chat.configure(state="disabled")

    def _build_input(self):
        frame = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=14)
        frame.pack(fill="x", padx=20, pady=(4, 18))
        self.entry = ctk.CTkTextbox(frame, height=70, font=("Segoe UI", 13),
                                    fg_color="transparent", wrap="word")
        self.entry.pack(side="left", fill="both", expand=True, padx=(12, 6), pady=8)
        self.entry.bind("<Control-Return>", lambda e: self.on_send())
        self.send_btn = ctk.CTkButton(frame, text="Send  ⏎", width=110, height=44,
                                      font=("Segoe UI Semibold", 13),
                                      fg_color=ACCENT, hover_color="#2563eb",
                                      command=self.on_send)
        self.send_btn.pack(side="right", padx=12, pady=12)
        ctk.CTkLabel(frame, text="Ctrl+Enter to send", text_color=FG_MUTED,
                     font=("Segoe UI", 10)).pack(side="right", padx=4)

    # ---------- helpers ----------
    def _append(self, text: str, tag: str = "system"):
        self.chat.configure(state="normal")
        self.chat.insert("end", text + "\n", tag)
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def _check_environment(self):
        self._append("── Environment check ──", "system")
        for name, path in [("Codex CLI", self.orch.codex_cli),
                           ("Claude Code CLI", self.orch.claude_cli),
                           ("VS Code CLI", self.orch.code_cli)]:
            status = f"✓ {path}" if path else "✗ NOT FOUND on PATH"
            self._append(f"  {name}: {status}", "system" if path else "error")
        self._append("Ready. Ask a question or request a task.\n", "system")

    def _set_stage(self, stage: str, state: str):
        self.after(0, lambda: self.stages[stage].set_state(state))

    # ---------- pipeline ----------
    def on_send(self):
        if self.busy:
            return
        prompt = self.entry.get("1.0", "end").strip()
        if not prompt:
            return
        self.entry.delete("1.0", "end")
        self.busy = True
        self.send_btn.configure(state="disabled", text="Working…")
        for s in self.stages.values():
            s.set_state("idle")

        ts = datetime.now().strftime("%H:%M:%S")
        self._append(f"\n[{ts}] 👤 You:\n{prompt}\n", "user")

        threading.Thread(target=self._worker, args=(prompt,), daemon=True).start()

    def _worker(self, prompt: str):
        open_vs = bool(self.vscode_switch.get())

        def on_stage(stage, state):
            self._set_stage(stage, state)
            if stage == "codex" and state == "done":
                self.after(0, lambda: self._append("🧠 Codex plan received, forwarding to Claude Code…", "system"))

        try:
            result = self.orch.run_pipeline(prompt, on_stage=on_stage, open_vscode=open_vs)
            self.after(0, lambda: self._show_result(result))
        except Exception as e:
            self.after(0, lambda: self._append(f"✗ Pipeline error: {e}", "error"))
        finally:
            self.after(0, self._done)

    def _show_result(self, r: PipelineResult):
        if r.codex_response:
            self._append("🧠 Codex (plan):", "codex")
            self._append(r.codex_response + "\n", "codex")
        if r.claude_response:
            self._append("⚙️ Claude Code (implementation):", "claude")
            self._append(r.claude_response + "\n", "claude")
        if r.md_file:
            self._append(f"📄 Spec file: {r.md_file}", "system")
            self._append("🚀 Opened in VS Code — use Copilot with Claude Fable 5 to implement the spec.\n", "system")
        for err in r.errors:
            self._append(f"✗ {err}", "error")

    def _done(self):
        self.busy = False
        self.send_btn.configure(state="normal", text="Send  ⏎")


if __name__ == "__main__":
    App().mainloop()
