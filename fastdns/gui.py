"""Clean, native desktop GUI for FastDNS (Linux & Windows)."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser
from typing import Optional

from .backends import BackendStatus, DnsBackend, create_backend
from .profiles import (
    DEFAULT_ROUTING_CATEGORIES,
    DnsProfile,
    ProfileStore,
    get_default_domains,
)
from .resolver import verify_profile_connectivity


# Professional Native Neutral Palette
BG_MAIN = "#1e1e1e"        # Window dark background
BG_PANEL = "#252526"       # Panel / Card background
BG_INPUT = "#2d2d30"       # Input / Combobox background
BORDER = "#3e3e42"         # Clean divider border
TEXT_PRI = "#cccccc"       # Normal text
TEXT_TITLE = "#ffffff"     # Highlighted text
TEXT_MUTED = "#858585"     # Subtitle / description
COLOR_ACCENT = "#007acc"    # Primary action blue
COLOR_GREEN = "#4ec9b0"     # Status active green
COLOR_RED = "#f14c4c"       # Warning / inactive red


def _make_modal(dlg: tk.Toplevel, parent: tk.Wm) -> None:
    """Safely make a Toplevel dialog modal across Windows and Linux (X11/Wayland)."""
    dlg.transient(parent)
    dlg.update_idletasks()
    try:
        dlg.wait_visibility()
    except tk.TclError:
        pass
    try:
        dlg.grab_set()
    except tk.TclError:
        pass


def _fit_window(win: tk.Wm, min_w: int = 420, min_h: int = 540) -> None:
    """Center window cleanly on screen."""
    win.update_idletasks()
    w = max(win.winfo_reqwidth() + 16, min_w)
    h = max(win.winfo_reqheight() + 16, min_h)
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    x = max((sw - w) // 2, 0)
    y = max((sh - h) // 3, 0)
    win.geometry(f"{w}x{h}+{x}+{y}")
    win.minsize(min_w, min_h)


class FastDnsApp:
    """FastDNS Desktop User Interface."""

    def __init__(
        self,
        root: tk.Tk,
        store: Optional[ProfileStore] = None,
        backend: Optional[DnsBackend] = None,
    ) -> None:
        self.root = root
        self.store = store or ProfileStore()
        self.backend = backend or create_backend()
        self.status: BackendStatus = BackendStatus(enabled=False, mode="inactive")
        self._busy = False

        self._configure_window()
        self._build_ui()
        self.refresh_state()
        _fit_window(self.root, min_w=440, min_h=560)

    def _configure_window(self) -> None:
        self.root.title("FastDNS")
        self.root.configure(bg=BG_MAIN)
        self.root.resizable(True, True)

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "Native.TCombobox",
            fieldbackground=BG_INPUT,
            background=BG_PANEL,
            foreground=TEXT_TITLE,
            arrowcolor=TEXT_PRI,
            bordercolor=BORDER,
            lightcolor=BG_INPUT,
            darkcolor=BG_INPUT,
            borderwidth=1,
            relief="solid",
        )
        style.map(
            "Native.TCombobox",
            fieldbackground=[("readonly", BG_INPUT)],
            foreground=[("readonly", TEXT_TITLE)],
            selectbackground=[("readonly", BG_INPUT)],
            selectforeground=[("readonly", TEXT_TITLE)],
            bordercolor=[("focus", COLOR_ACCENT), ("!focus", BORDER)],
        )
        self.root.option_add("*TCombobox*Listbox.background", BG_INPUT)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT_TITLE)
        self.root.option_add("*TCombobox*Listbox.selectBackground", COLOR_ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

    def _build_ui(self) -> None:
        font_family = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"

        main_box = tk.Frame(self.root, bg=BG_MAIN, padx=18, pady=16)
        main_box.pack(fill="both", expand=True)

        # 1. Header
        header = tk.Frame(main_box, bg=BG_MAIN)
        header.pack(fill="x", pady=(0, 14))

        tk.Label(
            header,
            text="FastDNS",
            font=(font_family, 14, "bold"),
            fg=TEXT_TITLE,
            bg=BG_MAIN,
        ).pack(side="left")

        os_tag = "Windows NRPT" if sys.platform == "win32" else "Linux systemd-resolved"
        tk.Label(
            header,
            text=os_tag,
            font=(font_family, 9),
            fg=TEXT_MUTED,
            bg=BG_MAIN,
        ).pack(side="right")

        # 2. Main Status & Toggle Panel
        status_panel = tk.Frame(
            main_box,
            bg=BG_PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
            padx=16,
            pady=16,
        )
        status_panel.pack(fill="x", pady=(0, 12))

        # Status indicator row
        status_row = tk.Frame(status_panel, bg=BG_PANEL)
        status_row.pack(fill="x", pady=(0, 10))

        self.status_dot = tk.Label(
            status_row,
            text="●",
            font=(font_family, 14),
            fg=COLOR_RED,
            bg=BG_PANEL,
        )
        self.status_dot.pack(side="left", padx=(0, 6))

        self.status_text = tk.Label(
            status_row,
            text="Disabled (System Default DNS)",
            font=(font_family, 11, "bold"),
            fg=TEXT_TITLE,
            bg=BG_PANEL,
        )
        self.status_text.pack(side="left")

        self.status_desc = tk.Label(
            status_panel,
            text="All traffic is resolved using your default network DNS.",
            font=(font_family, 9),
            fg=TEXT_MUTED,
            bg=BG_PANEL,
            anchor="w",
            justify="left",
            wraplength=380,
        )
        self.status_desc.pack(fill="x", pady=(0, 14))

        # Big clean action button
        self.toggle_btn = tk.Button(
            status_panel,
            text="Enable DNS",
            font=(font_family, 10, "bold"),
            fg="#ffffff",
            bg=COLOR_ACCENT,
            activeforeground="#ffffff",
            activebackground="#005999",
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            padx=16,
            pady=8,
            command=self.on_toggle_clicked,
        )
        self.toggle_btn.pack(fill="x")

        # 3. Settings Panel
        settings_panel = tk.Frame(
            main_box,
            bg=BG_PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
            padx=16,
            pady=14,
        )
        settings_panel.pack(fill="x", pady=(0, 12))

        # Profile selection
        prof_header = tk.Frame(settings_panel, bg=BG_PANEL)
        prof_header.pack(fill="x", pady=(0, 6))

        tk.Label(
            prof_header,
            text="Profile",
            font=(font_family, 9, "bold"),
            fg=TEXT_PRI,
            bg=BG_PANEL,
        ).pack(side="left")

        btn_box = tk.Frame(prof_header, bg=BG_PANEL)
        btn_box.pack(side="right")

        btn_folder = tk.Label(
            btn_box,
            text="Open Folder",
            font=(font_family, 8, "underline"),
            fg=TEXT_MUTED,
            bg=BG_PANEL,
            cursor="hand2",
        )
        btn_folder.pack(side="left", padx=(0, 8))
        btn_folder.bind("<Button-1>", lambda _e: self._open_profiles_folder())

        btn_reload = tk.Label(
            btn_box,
            text="Reload",
            font=(font_family, 8, "underline"),
            fg=TEXT_MUTED,
            bg=BG_PANEL,
            cursor="hand2",
        )
        btn_reload.pack(side="left", padx=(0, 8))
        btn_reload.bind("<Button-1>", lambda _e: self._reload_profiles())

        btn_add = tk.Label(
            btn_box,
            text="+ Add Profile",
            font=(font_family, 8, "underline"),
            fg=COLOR_ACCENT,
            bg=BG_PANEL,
            cursor="hand2",
        )
        btn_add.pack(side="left")
        btn_add.bind("<Button-1>", lambda _e: self._open_add_profile_dialog())

        self.profile_var = tk.StringVar()
        self.profile_combo = ttk.Combobox(
            settings_panel,
            textvariable=self.profile_var,
            state="readonly",
            style="Native.TCombobox",
            font=(font_family, 9),
        )
        self.profile_combo.pack(fill="x", pady=(0, 10))
        self.profile_combo.bind("<<ComboboxSelected>>", self._on_profile_selected)

        # Profile details summary
        self.endpoint_desc = tk.Label(
            settings_panel,
            text="",
            font=(font_family, 8),
            fg=TEXT_MUTED,
            bg=BG_PANEL,
            anchor="w",
            justify="left",
        )
        self.endpoint_desc.pack(fill="x", pady=(0, 12))

        # Scope selector (Conditional vs Global)
        scope_header = tk.Frame(settings_panel, bg=BG_PANEL)
        scope_header.pack(fill="x", pady=(0, 6))

        tk.Label(
            scope_header,
            text="Routing Scope",
            font=(font_family, 9, "bold"),
            fg=TEXT_PRI,
            bg=BG_PANEL,
        ).pack(side="left")

        scope_btns = tk.Frame(settings_panel, bg=BG_PANEL)
        scope_btns.pack(fill="x", pady=(0, 12))

        self.btn_scope_cond = tk.Button(
            scope_btns,
            text="Conditional (Google & AI)",
            font=(font_family, 8),
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            padx=10,
            pady=4,
            command=lambda: self._set_scope("conditional"),
        )
        self.btn_scope_cond.pack(side="left", expand=True, fill="x", padx=(0, 4))

        self.btn_scope_global = tk.Button(
            scope_btns,
            text="Global (All DNS)",
            font=(font_family, 8),
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            padx=10,
            pady=4,
            command=lambda: self._set_scope("global"),
        )
        self.btn_scope_global.pack(side="left", expand=True, fill="x", padx=(4, 0))

        # Engine selector (OS Native vs Hybrid DoH Proxy)
        engine_header = tk.Frame(settings_panel, bg=BG_PANEL)
        engine_header.pack(fill="x", pady=(0, 6))

        tk.Label(
            engine_header,
            text="DNS Engine",
            font=(font_family, 9, "bold"),
            fg=TEXT_PRI,
            bg=BG_PANEL,
        ).pack(side="left")

        engine_btns = tk.Frame(settings_panel, bg=BG_PANEL)
        engine_btns.pack(fill="x")

        self.btn_mode_native = tk.Button(
            engine_btns,
            text="OS-Native (DoT / NRPT)",
            font=(font_family, 8),
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            padx=10,
            pady=4,
            command=lambda: self._set_mode("native"),
        )
        self.btn_mode_native.pack(side="left", expand=True, fill="x", padx=(0, 4))

        self.btn_mode_hybrid = tk.Button(
            engine_btns,
            text="Local Proxy (DoH 443)",
            font=(font_family, 8),
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            padx=10,
            pady=4,
            command=lambda: self._set_mode("hybrid"),
        )
        self.btn_mode_hybrid.pack(side="left", expand=True, fill="x", padx=(4, 0))

        # 4. Utilities Row
        tools_frame = tk.Frame(main_box, bg=BG_MAIN)
        tools_frame.pack(fill="x", pady=(0, 10))

        self._create_tool_button(tools_frame, "Routing Rules", self._open_rules_dialog).pack(
            side="left", expand=True, fill="x", padx=(0, 4)
        )
        self._create_tool_button(tools_frame, "Test Connectivity", self._run_test).pack(
            side="left", expand=True, fill="x", padx=(4, 4)
        )
        self._create_tool_button(tools_frame, "MagicDNS Setup", self._open_setup_url).pack(
            side="left", expand=True, fill="x", padx=(4, 0)
        )

        # 5. Bottom Log Bar
        self.status_bar = tk.Label(
            main_box,
            text="Ready.",
            font=(font_family, 8),
            fg=TEXT_MUTED,
            bg=BG_MAIN,
            anchor="w",
        )
        self.status_bar.pack(fill="x")

        self._refresh_profile_selector()
        self._update_selectors()

    def _create_tool_button(self, parent: tk.Widget, text: str, command: object) -> tk.Button:
        font_family = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"
        return tk.Button(
            parent,
            text=text,
            font=(font_family, 8),
            fg=TEXT_PRI,
            bg=BG_INPUT,
            activeforeground=TEXT_TITLE,
            activebackground=BORDER,
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            padx=8,
            pady=5,
            command=command,  # type: ignore[arg-type]
        )

    def _open_profiles_folder(self) -> None:
        p_dir = self.store.profiles_dir
        p_dir.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(str(p_dir))
            elif sys.platform == "darwin":
                subprocess.run(["open", str(p_dir)], check=False)
            else:
                subprocess.run(["xdg-open", str(p_dir)], check=False)
        except Exception as exc:
            messagebox.showwarning("FastDNS", f"Could not open profiles folder:\n{p_dir}\n\n{exc}", parent=self.root)

    def _reload_profiles(self) -> None:
        self.store.reload_profiles()
        self._refresh_profile_selector()
        count = len(self.store.profiles)
        self.status_bar.configure(
            text=f"Profiles reloaded ({count} profile{'s' if count != 1 else ''} loaded)."
        )

    def _refresh_profile_selector(self) -> None:
        profiles = list(self.store.profiles.values())
        self._profile_id_by_label = {f"{p.name} ({p.primary_dns})": p.id for p in profiles}
        self._label_by_profile_id = {p.id: f"{p.name} ({p.primary_dns})" for p in profiles}
        self.profile_combo["values"] = list(self._profile_id_by_label.keys())

        active = self.store.active_profile
        curr_label = self._label_by_profile_id.get(active.id)
        if not curr_label and self.profile_combo["values"]:
            curr_label = self.profile_combo["values"][0]
            self.store.set_active_profile(self._profile_id_by_label[curr_label])
            active = self.store.active_profile
        if curr_label:
            self.profile_var.set(curr_label)
        self._update_profile_details(active)

    def _update_profile_details(self, profile: DnsProfile) -> None:
        lines = [
            f"Servers: {profile.primary_dns}" + (f", {profile.secondary_dns}" if profile.secondary_dns else ""),
            f"DoT: {profile.dot_endpoint or profile.dot_hostname or 'None'}  |  DoH: {profile.doh_url or 'None'}",
        ]
        self.endpoint_desc.configure(text="\n".join(lines))

    def _update_selectors(self) -> None:
        # Update Scope buttons
        if self.store.scope == "global":
            self.btn_scope_global.configure(
                bg=COLOR_ACCENT, fg="#ffffff", activebackground="#005999", activeforeground="#ffffff"
            )
            self.btn_scope_cond.configure(
                bg=BG_INPUT, fg=TEXT_MUTED, activebackground=BORDER, activeforeground=TEXT_TITLE
            )
        else:
            self.btn_scope_cond.configure(
                bg=COLOR_ACCENT, fg="#ffffff", activebackground="#005999", activeforeground="#ffffff"
            )
            self.btn_scope_global.configure(
                bg=BG_INPUT, fg=TEXT_MUTED, activebackground=BORDER, activeforeground=TEXT_TITLE
            )

        # Update Engine buttons
        if self.store.routing_mode == "hybrid":
            self.btn_mode_hybrid.configure(
                bg=COLOR_ACCENT, fg="#ffffff", activebackground="#005999", activeforeground="#ffffff"
            )
            self.btn_mode_native.configure(
                bg=BG_INPUT, fg=TEXT_MUTED, activebackground=BORDER, activeforeground=TEXT_TITLE
            )
        else:
            self.btn_mode_native.configure(
                bg=COLOR_ACCENT, fg="#ffffff", activebackground="#005999", activeforeground="#ffffff"
            )
            self.btn_mode_hybrid.configure(
                bg=BG_INPUT, fg=TEXT_MUTED, activebackground=BORDER, activeforeground=TEXT_TITLE
            )

    def _set_scope(self, scope: str) -> None:
        if self._busy or self.store.scope == scope:
            return
        self.store.scope = scope
        self.store.save()
        self._update_selectors()
        if self.status.enabled:
            self._apply_toggle(enable=True)

    def _set_mode(self, mode: str) -> None:
        if self._busy or self.store.routing_mode == mode:
            return
        self.store.routing_mode = mode
        self.store.save()
        self._update_selectors()
        if self.status.enabled:
            self._apply_toggle(enable=True)

    def _on_profile_selected(self, _event: object = None) -> None:
        label = self.profile_var.get()
        pid = self._profile_id_by_label.get(label)
        if not pid:
            return
        profile = self.store.set_active_profile(pid)
        self._update_profile_details(profile)
        if self.status.enabled and not self._busy:
            self._apply_toggle(enable=True)

    def refresh_state(self) -> None:
        profile = self.store.active_profile
        self.status = self.backend.get_status(profile)
        self._render_status()

    def _render_status(self) -> None:
        profile = self.store.active_profile
        if self._busy:
            self.status_dot.configure(fg="#e5c07b")
            self.status_text.configure(text="Applying changes...")
            self.toggle_btn.configure(state="disabled")
            return

        self.toggle_btn.configure(state="normal")
        if self.status.enabled:
            self.status_dot.configure(fg=COLOR_GREEN)
            scope_str = "Global (All Traffic)" if self.status.scope == "global" else "Conditional (Google & AI)"
            mode_str = "Local Proxy" if self.status.mode == "hybrid" else "DoT / NRPT"
            self.status_text.configure(text=f"Active • {profile.name}")
            self.status_desc.configure(
                text=f"Scope: {scope_str}\nEngine: {mode_str}"
            )
            self.toggle_btn.configure(text="Disable DNS", bg="#3a3d41", activebackground="#4c5055")
        else:
            self.status_dot.configure(fg=COLOR_RED)
            self.status_text.configure(text="Disabled (System Default DNS)")
            self.status_desc.configure(
                text="All traffic is resolved using your default network DNS."
            )
            self.toggle_btn.configure(text="Enable DNS", bg=COLOR_ACCENT, activebackground="#005999")

    def on_toggle_clicked(self) -> None:
        if self._busy:
            return
        self._apply_toggle(enable=not self.status.enabled)

    def _apply_toggle(self, enable: bool) -> None:
        self._busy = True
        self._render_status()

        profile = self.store.active_profile
        mode = self.store.routing_mode
        scope = self.store.scope

        def worker() -> None:
            err_msg: Optional[str] = None
            try:
                if enable:
                    new_status = self.backend.enable(profile, mode=mode, scope=scope)
                else:
                    new_status = self.backend.disable()
            except Exception as exc:
                err_msg = str(exc)
                new_status = self.backend.get_status(profile)

            def done() -> None:
                self._busy = False
                self.status = new_status
                self._render_status()
                if err_msg:
                    messagebox.showerror("FastDNS Error", err_msg, parent=self.root)
                else:
                    self.status_bar.configure(
                        text=f"Status: {'Active' if new_status.enabled else 'Disabled'}."
                    )

            self.root.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _run_test(self) -> None:
        profile = self.store.active_profile
        self.status_bar.configure(text=f"Testing {profile.name} endpoints...")

        def worker() -> None:
            report = verify_profile_connectivity(profile)

            def finish() -> None:
                if report.get("ok"):
                    ms = report.get("latency_ms")
                    self.status_bar.configure(text=f"Connected to {profile.name} ({ms} ms).")
                    lines = [
                        f"Profile: {profile.name}",
                        f"Average Latency: {ms} ms",
                        f"System Gemini Resolution: {report.get('system_gemini_ip')}",
                        "",
                        "Endpoint Probes:",
                    ]
                    for p in report.get("probes", []):
                        lines.append(f" • {p['domain']}: {p['status']} ({p['latency_ms']}) via {p['transport']}")
                    messagebox.showinfo("FastDNS Test Results", "\n".join(lines), parent=self.root)
                else:
                    self.status_bar.configure(text="Connection test failed.")
                    messagebox.showwarning("FastDNS Test", "Unable to connect to profile endpoints.", parent=self.root)

            self.root.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def _open_setup_url(self) -> None:
        profile = self.store.active_profile
        url = profile.setup_url or "https://magicdns.ru/#setup"
        webbrowser.open(url)

    def _open_rules_dialog(self) -> None:
        font_family = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"
        profile = self.store.active_profile
        dlg = tk.Toplevel(self.root)
        dlg.title("Routing Rules")
        dlg.configure(bg=BG_MAIN)

        top_box = tk.Frame(dlg, bg=BG_MAIN, padx=16, pady=14)
        top_box.pack(fill="both", expand=True)

        tk.Label(
            top_box,
            text=f"Conditionally Routed Domains ({len(profile.domains)})",
            font=(font_family, 10, "bold"),
            fg=TEXT_TITLE,
            bg=BG_MAIN,
        ).pack(anchor="w", pady=(0, 4))

        tk.Label(
            top_box,
            text="In Conditional mode, queries for these domains are routed through the profile.",
            font=(font_family, 8),
            fg=TEXT_MUTED,
            bg=BG_MAIN,
        ).pack(anchor="w", pady=(0, 10))

        # Add domain row
        add_box = tk.Frame(top_box, bg=BG_MAIN)
        add_box.pack(fill="x", pady=(0, 8))

        entry = tk.Entry(
            add_box,
            bg=BG_INPUT,
            fg=TEXT_TITLE,
            insertbackground=TEXT_TITLE,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=COLOR_ACCENT,
            font=(font_family, 9),
        )
        entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 6))

        list_box = tk.Frame(top_box, bg=BG_PANEL, highlightbackground=BORDER, highlightthickness=1)
        list_box.pack(fill="both", expand=True, pady=(0, 10))

        scrollbar = tk.Scrollbar(list_box)
        scrollbar.pack(side="right", fill="y")

        lb = tk.Listbox(
            list_box,
            bg=BG_PANEL,
            fg=TEXT_PRI,
            selectbackground=COLOR_ACCENT,
            selectforeground="#ffffff",
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=("Monospace", 9),
            yscrollcommand=scrollbar.set,
            height=12,
        )
        lb.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=lb.yview)

        def populate() -> None:
            lb.delete(0, tk.END)
            for d in profile.domains:
                lb.insert(tk.END, d)

        def add_domain() -> None:
            val = entry.get().strip().lower().lstrip(".")
            if val and val not in profile.domains:
                profile.domains.append(val)
                self.store.save()
                populate()
            entry.delete(0, tk.END)

        def remove_domain() -> None:
            sel = lb.curselection()
            if sel:
                d = lb.get(sel[0])
                if d in profile.domains:
                    profile.domains.remove(d)
                    self.store.save()
                    populate()

        def reset_domains() -> None:
            profile.domains = get_default_domains()
            self.store.save()
            populate()

        tk.Button(
            add_box,
            text="Add",
            font=(font_family, 8),
            fg="#ffffff",
            bg=COLOR_ACCENT,
            activeforeground="#ffffff",
            activebackground="#005999",
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            padx=10,
            command=add_domain,
        ).pack(side="right")

        btn_row = tk.Frame(top_box, bg=BG_MAIN)
        btn_row.pack(fill="x")

        tk.Button(
            btn_row,
            text="Remove Selected",
            font=(font_family, 8),
            fg=TEXT_PRI,
            bg=BG_INPUT,
            activeforeground=TEXT_TITLE,
            activebackground=BORDER,
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            padx=8,
            pady=4,
            command=remove_domain,
        ).pack(side="left", padx=(0, 6))

        tk.Button(
            btn_row,
            text="Reset Defaults",
            font=(font_family, 8),
            fg=TEXT_PRI,
            bg=BG_INPUT,
            activeforeground=TEXT_TITLE,
            activebackground=BORDER,
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            padx=8,
            pady=4,
            command=reset_domains,
        ).pack(side="left")

        tk.Button(
            btn_row,
            text="Close",
            font=(font_family, 8),
            fg=TEXT_PRI,
            bg=BG_INPUT,
            activeforeground=TEXT_TITLE,
            activebackground=BORDER,
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            padx=10,
            pady=4,
            command=dlg.destroy,
        ).pack(side="right")

        populate()
        _fit_window(dlg, min_w=440, min_h=460)
        _make_modal(dlg, self.root)

    def _open_add_profile_dialog(self) -> None:
        font_family = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"
        dlg = tk.Toplevel(self.root)
        dlg.title("Add Profile")
        dlg.configure(bg=BG_MAIN)

        box = tk.Frame(dlg, bg=BG_MAIN, padx=16, pady=14)
        box.pack(fill="both", expand=True)

        tk.Label(
            box,
            text="New DNS Profile",
            font=(font_family, 10, "bold"),
            fg=TEXT_TITLE,
            bg=BG_MAIN,
        ).pack(anchor="w", pady=(0, 10))

        fields = [
            ("Profile ID", "id", ""),
            ("Name", "name", ""),
            ("Primary IPv4", "primary_dns", ""),
            ("Secondary IPv4", "secondary_dns", ""),
            ("DoT Hostname", "dot_hostname", ""),
            ("DoH URL", "doh_url", ""),
        ]
        entries = {}
        for lbl_text, key, def_val in fields:
            tk.Label(
                box,
                text=lbl_text,
                font=(font_family, 8),
                fg=TEXT_MUTED,
                bg=BG_MAIN,
            ).pack(anchor="w")
            e = tk.Entry(
                box,
                bg=BG_INPUT,
                fg=TEXT_TITLE,
                insertbackground=TEXT_TITLE,
                relief="flat",
                bd=0,
                highlightthickness=1,
                highlightbackground=BORDER,
                highlightcolor=COLOR_ACCENT,
                font=(font_family, 9),
            )
            e.insert(0, def_val)
            e.pack(fill="x", ipady=3, pady=(2, 6))
            entries[key] = e

        def save() -> None:
            pid = entries["id"].get().strip().lower().replace(" ", "_")
            name = entries["name"].get().strip()
            p_ip = entries["primary_dns"].get().strip()
            s_ip = entries["secondary_dns"].get().strip()
            dot_h = entries["dot_hostname"].get().strip()
            doh_u = entries["doh_url"].get().strip()

            if not pid or not name or not p_ip:
                messagebox.showwarning("Validation", "ID, Name, and Primary DNS are required.", parent=dlg)
                return

            dot_ep = f"{p_ip}#{dot_h}" if dot_h else ""
            prof = DnsProfile(
                id=pid,
                name=name,
                primary_dns=p_ip,
                secondary_dns=s_ip,
                dot_hostname=dot_h,
                dot_endpoint=dot_ep,
                doh_url=doh_u,
                domains=get_default_domains(),
                builtin=False,
            )
            self.store.add_or_update_profile(prof)
            self.store.set_active_profile(pid)
            self._refresh_profile_selector()
            self._render_status()
            if self.status.enabled and not self._busy:
                self._apply_toggle(enable=True)
            dlg.destroy()

        b_row = tk.Frame(box, bg=BG_MAIN)
        b_row.pack(fill="x", pady=(8, 0))

        tk.Button(
            b_row,
            text="Save Profile",
            font=(font_family, 8),
            fg="#ffffff",
            bg=COLOR_ACCENT,
            activeforeground="#ffffff",
            activebackground="#005999",
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            padx=12,
            pady=4,
            command=save,
        ).pack(side="right")

        tk.Button(
            b_row,
            text="Cancel",
            font=(font_family, 8),
            fg=TEXT_PRI,
            bg=BG_INPUT,
            activeforeground=TEXT_TITLE,
            activebackground=BORDER,
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            padx=8,
            pady=4,
            command=dlg.destroy,
        ).pack(side="right", padx=(0, 6))

        dlg.bind("<Return>", lambda _e: save())
        dlg.bind("<Escape>", lambda _e: dlg.destroy())

        _fit_window(dlg, min_w=380, min_h=420)
        _make_modal(dlg, self.root)
        entries["id"].focus_set()


def run_gui() -> None:
    """Run FastDNS GUI."""
    root = tk.Tk()
    FastDnsApp(root)
    root.mainloop()
