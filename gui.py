#!/usr/bin/env python3
"""Standard-library desktop GUI for the DRL -> TAP converter (Windows/Linux)."""

from __future__ import annotations

import os
from pathlib import Path
from queue import Empty, Queue
import re
import subprocess
import sys
from threading import Thread
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from auto_convert import ROOT, find_inputs, run
from settings import (DEFAULTS, SETTINGS_NAME, SettingsError,
                      load_settings, save_settings, validate_settings)

CONFIG = ROOT / SETTINGS_NAME
PARAMETERS = (
    ("z_safe", "Безопасная высота Z (мм)"),
    ("z_approach", "Высота подхода Z (мм)"),
    ("z_drill", "Глубина сверления Z (мм)"),
    ("feed", "Подача по Z (мм/мин)"),
    ("spindle", "Скорость шпинделя (GRBL S)"),
    ("contour_step", "Шаг отверстий вдоль контура (мм)"),
    ("column_width", "Ширина вертикальной полосы (мм)"),
)
MOVE = re.compile(r"^G0 X([+-]?\d+(?:\.\d+)?) Y([+-]?\d+(?:\.\d+)?)$")


def parse_fields(values: dict[str, str]) -> dict:
    """Pure GUI-form parser; rejects non-numeric or inconsistent CNC settings."""
    parsed: dict = {}
    for key in ("z_safe", "z_approach", "z_drill", "feed",
                "contour_step", "column_width"):
        try:
            parsed[key] = float(values[key].strip().replace(",", "."))
        except (KeyError, ValueError, AttributeError) as exc:
            raise SettingsError(f"{key}: введите число") from exc
    try:
        parsed["spindle"] = int(values["spindle"].strip())
    except (KeyError, ValueError, AttributeError) as exc:
        raise SettingsError("spindle: введите целое число") from exc
    parsed["slot_mode"] = values.get("slot_mode", "drill")
    parsed["source_path"] = values.get("source_path", "").strip()
    parsed["output_dir"] = values.get("output_dir", "").strip()
    return validate_settings(parsed)


def read_positions(tap_file: Path) -> list[tuple[float, float]]:
    """Read only the XY *drilling moves* from the generated TAP for preview."""
    positions = []
    with tap_file.open("r", encoding="ascii") as file:
        for line in file:
            match = MOVE.fullmatch(line.strip())
            if match:
                positions.append((float(match.group(1)), float(match.group(2))))
    return positions


class ConverterWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("KiCad DRL → CNC3018 · TAP")
        root.geometry("920x850")
        root.minsize(750, 670)

        cfg = load_settings(CONFIG)
        self.vars = {key: tk.StringVar(value=str(value))
                     for key, value in cfg.items() if key != "slot_mode"}
        self.slot_mode = tk.StringVar(value=cfg["slot_mode"])
        self.events: Queue = Queue()
        self.busy = False
        self.last_output: Path | None = None
        self._make_widgets()
        self.root.after(150, self._check_events)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _make_widgets(self) -> None:
        body = ttk.Frame(self.root, padding=14)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="DRL → GRBL TAP", font=("Segoe UI", 17, "bold")).pack(anchor="w")
        ttk.Label(
            body,
            text="Один TAP на плату · вертикальная змейка · сверление точек контура · без пауз",
        ).pack(anchor="w", pady=(0, 12))

        source = ttk.LabelFrame(body, text="Исходные файлы и результат", padding=10)
        source.pack(fill="x", pady=4)
        source.columnconfigure(1, weight=1)

        ttk.Label(source, text="DRL / папка").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(source, textvariable=self.vars["source_path"]).grid(
            row=0, column=1, sticky="ew", padx=3)
        ttk.Button(source, text="DRL…", command=self._select_file).grid(row=0, column=2, padx=3)
        ttk.Button(source, text="Папка…", command=self._select_source_folder).grid(row=0, column=3, padx=3)
        ttk.Button(source, text="Автопоиск", command=lambda: self.vars["source_path"].set("")).grid(
            row=0, column=4, padx=3)

        ttk.Label(source, text="Каталог TAP").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(source, textvariable=self.vars["output_dir"]).grid(
            row=1, column=1, sticky="ew", padx=3, pady=(10, 0))
        ttk.Button(source, text="Выбрать…", command=self._select_output_folder).grid(
            row=1, column=2, columnspan=2, sticky="ew", padx=3, pady=(10, 0))
        ttk.Button(source, text="Рядом с DRL", command=lambda: self.vars["output_dir"].set("")).grid(
            row=1, column=4, padx=3, pady=(10, 0))

        parameters = ttk.LabelFrame(body, text="Параметры сверления", padding=10)
        parameters.pack(fill="x", pady=7)
        for index, (key, label) in enumerate(PARAMETERS):
            col = (index // 4) * 2
            row = index % 4
            ttk.Label(parameters, text=label).grid(
                row=row, column=col, sticky="w", padx=(5, 9), pady=6)
            ttk.Entry(parameters, textvariable=self.vars[key], width=13).grid(
                row=row, column=col + 1, sticky="ew", padx=(0, 20), pady=6)
        parameters.columnconfigure(1, weight=1)
        parameters.columnconfigure(3, weight=1)

        route = ttk.LabelFrame(body, text="Фрезеруемые пазы / контуры из DRL", padding=10)
        route.pack(fill="x", pady=5)
        for text, value in (
            ("Высверливать вдоль контура", "drill"),
            ("Игнорировать контуры", "skip"),
            ("Останавливать обработку при контурах", "strict"),
        ):
            ttk.Radiobutton(route, text=text, variable=self.slot_mode,
                            value=value).pack(side="left", padx=(0, 18))

        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(12, 6))
        self.convert_button = ttk.Button(actions, text="Создать TAP", command=self._start)
        self.convert_button.pack(side="left", padx=(0, 7))
        self.save_button = ttk.Button(actions, text="Сохранить настройки", command=self._save)
        self.save_button.pack(side="left", padx=7)
        ttk.Button(actions, text="По умолчанию", command=self._defaults).pack(side="left", padx=7)
        ttk.Button(actions, text="Открыть TAP", command=self._open_output).pack(side="right", padx=4)
        self.status = tk.StringVar(value=f"Настройки: {CONFIG.name}. Готово к обработке.")
        ttk.Label(body, textvariable=self.status).pack(anchor="w", pady=(0, 7))

        preview_frame = ttk.LabelFrame(body, text="Траектория XY (предпросмотр)", padding=7)
        preview_frame.pack(fill="both", expand=True, pady=5)
        self.canvas = tk.Canvas(preview_frame, background="#fafafa",
                                highlightthickness=1, highlightbackground="#d0d0d0",
                                height=195)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda event: self._draw_preview())
        self.preview_points: list[tuple[float, float]] = []
        self.preview_label = tk.StringVar(value="После конвертации здесь появится траектория перемещений XY")
        ttk.Label(preview_frame, textvariable=self.preview_label).pack(anchor="w", pady=(5, 0))

        report = ttk.LabelFrame(body, text="Протокол конвертации", padding=7)
        report.pack(fill="both", expand=True, pady=(5, 0))
        self.log = tk.Text(report, height=9, wrap="word", font=("Consolas", 9))
        scrollbar = ttk.Scrollbar(report, command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self._show_log("Готово. Выберите DRL или папку, затем нажмите «Создать TAP».\n"
                       "Пустое поле источника = автоматический поиск рядом с программой и в input/.\n"
                       "Проверьте траектории в Candle/UGS до запуска станка.")

    def _select_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Выберите файл сверловки", filetypes=[("KiCad DRL", "*.drl"), ("Все файлы", "*.*")])
        if selected:
            self.vars["source_path"].set(selected)

    def _select_source_folder(self) -> None:
        selected = filedialog.askdirectory(title="Выберите папку с DRL")
        if selected:
            self.vars["source_path"].set(selected)

    def _select_output_folder(self) -> None:
        selected = filedialog.askdirectory(title="Куда сохранять TAP")
        if selected:
            self.vars["output_dir"].set(selected)

    def _form_data(self) -> dict:
        values = {key: var.get() for key, var in self.vars.items()}
        values["slot_mode"] = self.slot_mode.get()
        return parse_fields(values)

    def _save(self) -> bool:
        try:
            save_settings(CONFIG, self._form_data())
        except (SettingsError, OSError) as exc:
            messagebox.showerror("Ошибка настроек", str(exc))
            return False
        self.status.set(f"Настройки сохранены в {CONFIG.name}")
        return True

    def _defaults(self) -> None:
        if self.busy:
            return
        for key, value in DEFAULTS.items():
            if key == "slot_mode":
                self.slot_mode.set(value)
            else:
                self.vars[key].set(str(value))
        self.status.set("Значения по умолчанию восстановлены в форме; нажмите «Сохранить настройки».")

    def _show_log(self, value: str) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("end", value)
        self.log.configure(state="disabled")

    def _start(self) -> None:
        if self.busy or not self._save():
            return
        self.busy = True
        self.convert_button.configure(state="disabled")
        self.save_button.configure(state="disabled")
        self.status.set("Конвертация выполняется…")
        self._show_log("Идёт обработка файлов. После завершения появится отчёт.")
        Thread(target=self._worker, daemon=True).start()

    def _worker(self) -> None:
        try:
            result = run([], root=ROOT)
            file = ROOT / "conversion_report.txt"
            contents = file.read_text(encoding="utf-8-sig") if file.exists() else "Отчёт не создан."
            self.events.put((result, contents))
        except Exception as exc:
            self.events.put((1, f"Непредвиденная ошибка: {exc}"))

    def _check_events(self) -> None:
        try:
            result, contents = self.events.get_nowait()
        except Empty:
            pass
        else:
            self.busy = False
            self.convert_button.configure(state="normal")
            self.save_button.configure(state="normal")
            self._show_log(contents)
            self.status.set("Готово: TAP созданы." if result == 0 else
                            "Обработка завершилась с ошибкой. Смотрите протокол.")
            if result == 0:
                self._load_preview()
        self.root.after(150, self._check_events)

    def _candidate_outputs(self) -> list[Path]:
        data = self._form_data()
        directory = Path(data["output_dir"]).expanduser() if data["output_dir"] else None
        if directory is not None and not directory.is_absolute():
            directory = ROOT / directory
        if directory is not None:
            return sorted(directory.glob("*.tap"))
        source = data["source_path"]
        explicit = [Path(source).expanduser()] if source else []
        if explicit and not explicit[0].is_absolute():
            explicit = [ROOT / explicit[0]]
        try:
            sources = find_inputs(explicit, ROOT)
        except (OSError, ValueError):
            return []
        return [p.with_suffix(".tap") for p in sources if p.with_suffix(".tap").is_file()]

    def _load_preview(self) -> None:
        for target in self._candidate_outputs():
            try:
                points = read_positions(target)
            except (OSError, UnicodeError, ValueError):
                continue
            if points:
                self.preview_points = points
                self.last_output = target.parent
                self.preview_label.set(f"{target.name} — {len(points)} точек сверления"
                                       " (линии показывают холостые перемещения XY)")
                self._draw_preview()
                return
        self.preview_points = []
        self.preview_label.set("Готовая траектория для предпросмотра не найдена.")
        self._draw_preview()

    def _draw_preview(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        points = self.preview_points
        if not points:
            canvas.create_text(max(canvas.winfo_width() // 2, 100), 90,
                               text="Нет траектории", fill="#666")
            return
        w = max(canvas.winfo_width(), 200)
        h = max(canvas.winfo_height(), 130)
        margin = 25
        min_x, max_x = min(p[0] for p in points), max(p[0] for p in points)
        min_y, max_y = min(p[1] for p in points), max(p[1] for p in points)
        width = max(max_x - min_x, 0.01)
        height = max(max_y - min_y, 0.01)
        scale = min((w - 2 * margin) / width, (h - 2 * margin) / height)
        xy = [(margin + (x - min_x) * scale,
               h - margin - (y - min_y) * scale) for x, y in points]
        # A point is a drill plunge. Connecting lines are only rapid XY moves.
        if len(xy) > 1:
            canvas.create_line(*[n for p in xy for n in p], fill="#9ba8b3", width=1)
        stride = max(1, len(xy) // 1200)
        for x, y in xy[::stride]:
            canvas.create_oval(x - 2, y - 2, x + 2, y + 2,
                               fill="#33699a", outline="")
        for index, color in ((0, "#24944b"), (-1, "#c73f3f")):
            x, y = xy[index]
            canvas.create_oval(x - 5, y - 5, x + 5, y + 5,
                               fill=color, outline="white", width=1)

    def _open_output(self) -> None:
        try:
            if self.last_output and self.last_output.is_dir():
                folder = self.last_output
            else:
                settings = self._form_data()
                raw = settings["output_dir"] or settings["source_path"]
                folder = Path(raw).expanduser() if raw else ROOT / "input"
                if not folder.is_absolute():
                    folder = ROOT / folder
                if folder.is_file():
                    folder = folder.parent
                if not folder.is_dir():
                    folder = ROOT
            if sys.platform == "win32":
                os.startfile(str(folder))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except (OSError, ValueError, SettingsError) as exc:
            messagebox.showerror("Не удалось открыть папку", str(exc))

    def _close(self) -> None:
        if self.busy:
            messagebox.showwarning("Выполняется конвертация",
                                   "Дождитесь завершения конвертации перед закрытием окна.")
            return
        self.root.destroy()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["--check"]:
        # Headless CI/import smoke test: checks Tk import and default JSON.
        validate_settings(load_settings(CONFIG))
        print("GUI imports and settings: OK")
        return 0
    if argv:
        print("Использование: python gui.py [--check]", file=sys.stderr)
        return 2
    try:
        window = tk.Tk()
        ConverterWindow(window)
        window.mainloop()
    except (SettingsError, tk.TclError) as exc:
        print(f"Ошибка запуска GUI: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
