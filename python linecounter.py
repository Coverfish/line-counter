#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime
import sqlite3
import tkinter as tk
from tkinter import ttk


DB_NAME = "line_history.db"


# ------------------ data collection ------------------ #

def count_lines_in_file(path: Path) -> tuple[int, int]:
    """Return (total_lines, non_empty_lines) for a given file."""
    total = 0
    non_empty = 0

    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            total += 1
            if line.strip():
                non_empty += 1

    return total, non_empty


SUPPORTED_EXTENSIONS = {".py", ".c", ".h", ".cpp", ".hpp"}

def collect_stats(folder: Path, exclude_name: str):
    file_stats: list[tuple[str, int, int]] = []
    total_lines = 0
    total_non_empty = 0

    for item in sorted(folder.iterdir()):
        if (
            item.is_file()
            and item.suffix in SUPPORTED_EXTENSIONS
            and item.name != exclude_name
        ):
            file_total, file_non_empty = count_lines_in_file(item)
            file_stats.append((item.name, file_total, file_non_empty))
            total_lines += file_total
            total_non_empty += file_non_empty

    return file_stats, total_lines, total_non_empty

# ------------------ database helpers ------------------ #

def init_db(db_path: Path):
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshot_line (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                total_lines INTEGER NOT NULL,
                non_empty_lines INTEGER NOT NULL,
                FOREIGN KEY(snapshot_id) REFERENCES snapshot(id)
            );
            """
        )
        conn.commit()


def save_snapshot(db_path: Path, file_stats):
    """Insert a new snapshot and its file stats."""
    timestamp = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO snapshot (timestamp) VALUES (?);", (timestamp,))
        snapshot_id = cur.lastrowid
        cur.executemany(
            """
            INSERT INTO snapshot_line
                (snapshot_id, filename, total_lines, non_empty_lines)
            VALUES (?, ?, ?, ?);
            """,
            [
                (snapshot_id, name, total, non_empty)
                for (name, total, non_empty) in file_stats
            ],
        )
        conn.commit()
    return snapshot_id, timestamp


def load_snapshots(db_path: Path, exclude_name: str):
    """
    Load all snapshots with their file stats.

    Returns list of dicts:
      {
        "id": int,
        "timestamp": str,
        "files": [(filename, total, non_empty), ...]
      }
    """
    if not db_path.exists():
        return []

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT s.id, s.timestamp, l.filename, l.total_lines, l.non_empty_lines
            FROM snapshot s
            JOIN snapshot_line l ON l.snapshot_id = s.id
            ORDER BY s.id, l.filename;
            """
        )
        rows = cur.fetchall()

    snapshots = []
    current = None
    last_id = None

    for snap_id, ts, filename, total, non_empty in rows:
        if filename == exclude_name:
            continue  # filter this script out of old snapshots too
        if snap_id != last_id:
            if current is not None:
                snapshots.append(current)
            current = {"id": snap_id, "timestamp": ts, "files": []}
            last_id = snap_id
        current["files"].append((filename, total, non_empty))

    if current is not None:
        snapshots.append(current)

    return snapshots


# ------------------ Snapshots tab: colored text ------------------ #

def populate_snapshots_text(text: tk.Text, snapshots):
    text.config(state="normal")
    text.delete("1.0", "end")

    # Define tags for colors
    text.tag_configure("header", foreground="#d16fff")       # purple
    text.tag_configure("total", foreground="#e4e261")        # yellow-ish
    text.tag_configure("nonempty", foreground="#7cd67c")     # green-ish
    text.tag_configure("title", foreground="#d16fff",
                       font=("TkDefaultFont", 10, "bold"))
    text.tag_configure("weekday", foreground="#4a8bff",
                       font=("TkDefaultFont", 10, "bold"))

    if not snapshots:
        text.insert("end", "No snapshots yet. Run the script again to create one.")
        text.config(state="disabled")
        return

    n = len(snapshots)

    # Figure out which snapshot index (in chronological order) is the LAST of each day
    # snapshots is chronological (oldest -> newest)
    last_index_for_date = {}
    for idx, snap in enumerate(snapshots):
        ts = snap["timestamp"]
        date_str = ts.split("T", 1)[0]  # 'YYYY-MM-DD'
        last_index_for_date[date_str] = idx  # overwrite -> last one wins

    # newest snapshot first in display
    for i, snap in enumerate(reversed(snapshots)):
        orig_idx = n - 1 - i  # index in original list
        ts = snap["timestamp"]
        date_str = ts.split("T", 1)[0]

        is_last_of_day = (last_index_for_date.get(date_str) == orig_idx)
        weekday_str = ""
        if is_last_of_day:
            try:
                weekday_str = datetime.fromisoformat(ts).strftime("%A").upper()
            except ValueError:
                weekday_str = ""

        idx_display = n - i  # keep numbering chronological
        # header line: title + optional weekday tag
        title_text = f"Snapshot {idx_display} - {ts}"
        text.insert("end", title_text, "title")
        if weekday_str:
            text.insert("end", "  ")
            text.insert("end", weekday_str, "weekday")
        text.insert("end", "\n")

        file_stats = snap["files"]

        if not file_stats:
            text.insert("end", "(no files)\n\n")
            continue

        name_width = max(len(name) for name, *_ in file_stats) + 2
        header = (
            f"{'File':<{name_width}}"
            f"{'Total':>10}  "
            f"{'Non-empty':>12}  "
            f"{'Code %':>7}"
        )
        text.insert("end", header + "\n", "header")
        text.insert("end", "-" * len(header) + "\n")

        total_all = 0
        total_non_empty_all = 0

        for name, total, non_empty in file_stats:
            pct = (non_empty / total * 100) if total else 0.0

            # filename
            text.insert("end", f"{name:<{name_width}}")

            # total
            total_str = f"{total:>10}"
            text.insert("end", total_str, "total")
            text.insert("end", "  ")

            # non-empty
            non_str = f"{non_empty:>12}"
            text.insert("end", non_str, "nonempty")
            text.insert("end", "  ")

            # percentage
            pct_str = f"{pct:6.1f}%"
            text.insert("end", pct_str + "\n")

            total_all += total
            total_non_empty_all += non_empty

        text.insert("end", "\n")
        prefix = "Total lines (including empty): "
        text.insert("end", prefix)
        text.insert("end", f"{total_all}\n", "total")

        prefix = "Total non-empty lines:        "
        text.insert("end", prefix)
        text.insert("end", f"{total_non_empty_all}\n", "nonempty")

        text.insert("end", "=" * len(header) + "\n\n")

    text.config(state="disabled")


# ------------------ Graph tab helpers ------------------ #

def snapshot_to_map(snapshot):
    """Return {filename: total_lines} for a snapshot."""
    return {name: total for (name, total, _non_empty) in snapshot["files"]}


def build_gui(snapshots):
    root = tk.Tk()
    root.title("Line Counter - Snapshots & Graph")

    # Window size that fits but never exceeds screen
    target_w, target_h = 1700, 1000
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    margin = 100

    max_w = max(800, screen_w - margin)
    max_h = max(600, screen_h - margin)

    win_w = min(target_w, max_w)
    win_h = min(target_h, max_h)

    x = (screen_w // 2) - (win_w // 2)
    y = (screen_h // 2) - (win_h // 2)
    root.geometry(f"{win_w}x{win_h}+{x}+{y}")

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)

    # ---------- Tab 1: Snapshots ---------- #
    frame_snapshots = ttk.Frame(notebook)
    notebook.add(frame_snapshots, text="Snapshots (F1)")

    text = tk.Text(frame_snapshots, wrap="none")
    scroll_y_snap = ttk.Scrollbar(
        frame_snapshots, orient="vertical", command=text.yview
    )
    text.configure(yscrollcommand=scroll_y_snap.set)

    text.pack(side="left", fill="both", expand=True)
    scroll_y_snap.pack(side="right", fill="y")

    populate_snapshots_text(text, snapshots)

    # ---------- Tab 2: Graph (horizontal bar chart + scrollbar) ---------- #
    frame_graph = ttk.Frame(notebook)
    notebook.add(frame_graph, text="Graph (F2)")

    control_frame = ttk.Frame(frame_graph)
    control_frame.pack(side="top", fill="x")

    snapshot_info_label = ttk.Label(control_frame, text="No snapshots available.")
    snapshot_info_label.pack(side="left", padx=10, pady=5)

    btn_prev = ttk.Button(control_frame, text="▲ snapshot")  # newer
    btn_next = ttk.Button(control_frame, text="▼ snapshot")  # older
    btn_next.pack(side="right", padx=5, pady=5)
    btn_prev.pack(side="right", padx=5, pady=5)

    # Canvas + scrollbar for graph
    graph_container = ttk.Frame(frame_graph)
    graph_container.pack(side="top", fill="both", expand=True, padx=10, pady=10)

    canvas = tk.Canvas(graph_container, bg="white")
    scroll_y_graph = ttk.Scrollbar(
        graph_container, orient="vertical", command=canvas.yview
    )
    canvas.configure(yscrollcommand=scroll_y_graph.set)

    canvas.pack(side="left", fill="both", expand=True)
    scroll_y_graph.pack(side="right", fill="y")

    # Track which snapshot we're viewing (0 = oldest, len-1 = newest)
    if snapshots:
        current_index = tk.IntVar(value=len(snapshots) - 1)
    else:
        current_index = tk.IntVar(value=0)

    def update_graph(*_args):
        canvas.delete("all")

        if not snapshots:
            snapshot_info_label.config(text="No snapshots available.")
            canvas.create_text(
                10, 10, anchor="nw", text="No snapshots available."
            )
            canvas.config(scrollregion=(0, 0, 0, 0))
            return

        idx = current_index.get()
        idx = max(0, min(idx, len(snapshots) - 1))
        current_index.set(idx)

        current = snapshots[idx]
        # For index 0, there's no "previous" snapshot, so blue=current and no red/green.
        if idx == 0:
            base_map = snapshot_to_map(current)
        else:
            prev = snapshots[idx - 1]
            base_map = snapshot_to_map(prev)

        curr_map = snapshot_to_map(current)

        snapshot_info_label.config(
            text=(
                f"Showing snapshot {idx + 1} of {len(snapshots)} "
                f"(timestamp {current['timestamp']})"
            )
        )

        filenames = sorted(set(base_map.keys()) | set(curr_map.keys()))
        if not filenames:
            canvas.create_text(10, 10, anchor="nw", text="No file data.")
            canvas.config(scrollregion=(0, 0, 0, 0))
            return

        max_total = 0
        for fn in filenames:
            prev_total = base_map.get(fn, 0)
            curr_total = curr_map.get(fn, 0)
            max_total = max(max_total, prev_total, curr_total)

        if max_total == 0:
            canvas.create_text(10, 10, anchor="nw", text="All totals are zero.")
            canvas.config(scrollregion=(0, 0, 0, 0))
            return

        # Canvas width (height we'll scroll via scrollregion)
        w = canvas.winfo_width() or 900

        margin_left = 220   # space for filenames
        margin_right = 40
        margin_top = 140    # start bars below totals + legend
        margin_bottom = 40

        graph_width = max(200, w - margin_left - margin_right)

        bar_height = 22
        bar_gap = 8
        total_bar_height = len(filenames) * (bar_height + bar_gap)

        # --- project totals for this snapshot (numbers only) ---
        total_all = sum(total for _n, total, _ne in current["files"])
        total_non_empty_all = sum(ne for _n, _t, ne in current["files"])

        canvas.create_text(
            margin_left,
            10,
            anchor="nw",
            text=f"Total lines (including empty): {total_all}",
            font=("TkDefaultFont", 10, "bold"),
        )
        canvas.create_text(
            margin_left,
            28,
            anchor="nw",
            text=f"Total non-empty lines:        {total_non_empty_all}",
            font=("TkDefaultFont", 10, "bold"),
        )

        # Legend
        legend_y = 60
        legend_x = margin_left

        canvas.create_rectangle(
            legend_x, legend_y, legend_x + 20, legend_y + 15,
            fill="#4a90e2", outline="black"
        )
        canvas.create_text(
            legend_x + 25, legend_y + 8,
            text="Baseline lines (prev snapshot or current for first)",
            anchor="w",
            font=("TkDefaultFont", 9),
        )

        canvas.create_rectangle(
            legend_x, legend_y + 22, legend_x + 20, legend_y + 37,
            fill="#e94d4d", outline="black"
        )
        canvas.create_text(
            legend_x + 25, legend_y + 30,
            text="New lines in this snapshot",
            anchor="w",
            font=("TkDefaultFont", 9),
        )

        canvas.create_rectangle(
            legend_x, legend_y + 44, legend_x + 20, legend_y + 59,
            fill="#7cd67c", outline="black"
        )
        canvas.create_text(
            legend_x + 25, legend_y + 52,
            text="Removed lines vs previous",
            anchor="w",
            font=("TkDefaultFont", 9),
        )

        # Horizontal scale
        scale = graph_width / max_total if max_total else 0

        # Draw horizontal bars
        for i, fn in enumerate(filenames):
            y_top = margin_top + i * (bar_height + bar_gap)
            y_bottom = y_top + bar_height

            prev_total = base_map.get(fn, 0)
            curr_total = curr_map.get(fn, 0)

            x_start = margin_left

            if idx == 0:
                # First snapshot: just blue current bar
                base_value = curr_total
                base_width = base_value * scale

                x_curr_end = x_start + base_width

                canvas.create_rectangle(
                    x_start, y_top, x_curr_end, y_bottom,
                    fill="#4a90e2", outline="black"
                )
            else:
                diff = curr_total - prev_total

                if diff > 0:
                    # Grew: blue = previous total, red = added
                    base_value = prev_total
                    added_value = diff
                    base_width = base_value * scale
                    added_width = added_value * scale

                    x_prev_end = x_start + base_width
                    x_curr_end = x_prev_end + added_width

                    # Blue base (previous snapshot)
                    canvas.create_rectangle(
                        x_start, y_top, x_prev_end, y_bottom,
                        fill="#4a90e2", outline="black"
                    )
                    # Red added
                    canvas.create_rectangle(
                        x_prev_end, y_top, x_curr_end, y_bottom,
                        fill="#e94d4d", outline="black"
                    )
                elif diff < 0:
                    # Shrunk: blue = current total, green = removed part
                    removed_value = -diff
                    base_value = curr_total
                    base_width = base_value * scale
                    removed_width = removed_value * scale

                    x_curr_end = x_start + base_width
                    x_prev_end = x_curr_end + removed_width

                    # Blue base (current snapshot)
                    canvas.create_rectangle(
                        x_start, y_top, x_curr_end, y_bottom,
                        fill="#4a90e2", outline="black"
                    )
                    # Green removed part
                    canvas.create_rectangle(
                        x_curr_end, y_top, x_prev_end, y_bottom,
                        fill="#7cd67c", outline="black"
                    )
                else:
                    # Same size: just blue bar
                    base_value = curr_total
                    base_width = base_value * scale
                    x_curr_end = x_start + base_width

                    canvas.create_rectangle(
                        x_start, y_top, x_curr_end, y_bottom,
                        fill="#4a90e2", outline="black"
                    )

            # Current total label (at end of current value)
            x_label = x_start + curr_total * scale + 5
            canvas.create_text(
                x_label, (y_top + y_bottom) / 2,
                text=str(curr_total),
                anchor="w",
                font=("TkDefaultFont", 8),
            )

            # Filename label (left of bar)
            canvas.create_text(
                margin_left - 10, (y_top + y_bottom) / 2,
                text=fn,
                anchor="e",
                font=("TkDefaultFont", 8),
            )

        total_height = margin_top + total_bar_height + margin_bottom
        canvas.config(scrollregion=(0, 0, w, total_height))

    # Original go_prev/go_next (older/newer), then we wire them reversed to buttons/keys
    def go_prev():
        # previous = older snapshot (index-1)
        if not snapshots:
            return
        if notebook.index(notebook.select()) != 1:
            return
        current_index.set(max(0, current_index.get() - 1))
        update_graph()

    def go_next():
        # next = newer snapshot (index+1)
        if not snapshots:
            return
        if notebook.index(notebook.select()) != 1:
            return
        current_index.set(min(len(snapshots) - 1, current_index.get() + 1))
        update_graph()

    # Reverse wiring: ▲/Up = go_next (newer),
    # ▼/Down = go_prev (older)
    btn_prev.config(command=go_next)   # ▲
    btn_next.config(command=go_prev)   # ▼

    canvas.bind("<Configure>", lambda event: update_graph())

    # Tab switching with F1/F2
    def select_snapshots(_event=None):
        notebook.select(0)

    def select_graph(_event=None):
        notebook.select(1)

    root.bind("<F1>", select_snapshots)
    root.bind("<F2>", select_graph)

    # Arrow keys for snapshot navigation in Graph tab (reversed)
    root.bind("<Up>", lambda event: go_next())
    root.bind("<Down>", lambda event: go_prev())

    # Status bar
    status = ttk.Label(
        root,
        text="F1: Snapshots | F2: Graph | ▲/Up: newer snapshot | ▼/Down: older snapshot (Graph tab)",
        anchor="w",
    )
    status.pack(fill="x", side="bottom")

    update_graph()
    root.mainloop()


# ------------------ main ------------------ #

def main():
    script_path = Path(__file__).resolve()
    folder = script_path.parent
    db_path = folder / DB_NAME
    script_name = script_path.name

    # DB initialisieren
    init_db(db_path)

    # Aktuelle Stats holen
    file_stats, total_lines, total_non_empty = collect_stats(folder, script_name)

    # Bisherige Snapshots laden
    snapshots = load_snapshots(db_path, script_name)

    # Entscheiden, ob ein neuer Snapshot nötig ist
    create_new = True
    if snapshots:
        last_files = snapshots[-1]["files"]  # already sorted by filename
        if len(last_files) == len(file_stats) and all(
            lf == fs for lf, fs in zip(last_files, file_stats)
        ):
            create_new = False

    if create_new:
        save_snapshot(db_path, file_stats)
        snapshots = load_snapshots(db_path, script_name)

    # GUI starten (mit alten oder neuen Snapshots)
    build_gui(snapshots)


if __name__ == "__main__":
    main()
