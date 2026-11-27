# capture_tool.py
import time
import cv2
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import engine
from app_store import catalog

def open_capture_dialog(parent, window_title, log_fn, on_saved):
    try:
        game = engine.GameWindow(window_title)
        game.focus()
        time.sleep(0.6)
        img = game.screenshot()
    except Exception as e:
        messagebox.showerror("Can't capture", str(e))
        return

    h, w = img.shape[:2]
    pil_full = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    top = tk.Toplevel(parent)
    top.title("Drag a box, pick a name, Save (stays open for more). Wheel = zoom, right-drag = move")

    sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
    win_w, win_h = min(w + 40, sw - 60), sh - 130
    top.geometry(f"{win_w}x{win_h}+{(sw - win_w) // 2}+10")
    top.bind("<Escape>", lambda _e: top.destroy())

    bar = ttk.Frame(top)
    bar.pack(side="bottom", fill="x", padx=8, pady=6)
    frame = ttk.Frame(top)
    frame.pack(side="top", fill="both", expand=True)
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    canvas = tk.Canvas(frame, cursor="cross", highlightthickness=0, bg="#202020")
    vbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
    hbar = ttk.Scrollbar(frame, orient="horizontal", command=canvas.xview)
    canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    vbar.grid(row=0, column=1, sticky="ns")
    hbar.grid(row=1, column=0, sticky="ew")

    MIN_Z, MAX_Z = 0.2, 6.0
    fit = max(MIN_Z, min(1.0, (win_w - 30) / w, (win_h - 110) / h))
    state = {"zoom": fit}
    sel = {"start": None, "box": None}
    zoom_var = tk.StringVar()

    def render(zoom, anchor=None):
        zoom = max(MIN_Z, min(MAX_Z, zoom))
        state["zoom"] = zoom
        size = (max(1, int(w * zoom)), max(1, int(h * zoom)))
        pil = pil_full.resize(size, Image.BILINEAR if zoom < 1 else Image.NEAREST)
        photo = ImageTk.PhotoImage(pil)
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=photo)
        canvas.image = photo
        canvas.configure(scrollregion=(0, 0, size[0], size[1]))
        zoom_var.set(f"{int(round(zoom * 100))}%")
        draw_box()
        if anchor:
            wx, wy, ix, iy = anchor
            canvas.xview_moveto(max(0.0, (ix * zoom - wx) / size[0]))
            canvas.yview_moveto(max(0.0, (iy * zoom - wy) / size[1]))

    def draw_box():
        canvas.delete("selbox")
        if sel["box"]:
            z = state["zoom"]
            x1, y1, x2, y2 = [v * z for v in sel["box"]]
            canvas.create_rectangle(x1, y1, x2, y2, outline="red", width=2, tags="selbox")

    def to_img(e):
        z = state["zoom"]
        return (max(0, min(w, canvas.canvasx(e.x) / z)), max(0, min(h, canvas.canvasy(e.y) / z)))

    def zoom_by(factor, wx=None, wy=None):
        if wx is None:
            wx, wy = canvas.winfo_width() / 2, canvas.winfo_height() / 2
        z = state["zoom"]
        render(z * factor, anchor=(wx, wy, canvas.canvasx(wx) / z, canvas.canvasy(wy) / z))

    def wheel(e):
        zoom_by(1.25 if e.delta > 0 else 0.8, e.x, e.y)

    def press(e):
        sel["start"] = to_img(e)
        sel["box"] = None
        draw_box()

    def drag(e):
        if not sel["start"]:
            return
        x1, y1 = sel["start"]
        x2, y2 = to_img(e)
        sel["box"] = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        draw_box()

    canvas.bind("<MouseWheel>", wheel)
    canvas.bind("<ButtonPress-1>", press)
    canvas.bind("<B1-Motion>", drag)
    canvas.bind("<ButtonRelease-1>", drag)
    for btn in (2, 3):
        canvas.bind(f"<ButtonPress-{btn}>", lambda e: canvas.scan_mark(e.x, e.y))
        canvas.bind(f"<B{btn}-Motion>", lambda e: canvas.scan_dragto(e.x, e.y, gain=1))

    ttk.Button(bar, text="-", width=3, command=lambda: zoom_by(0.8)).pack(side="left")
    ttk.Label(bar, textvariable=zoom_var, width=6, anchor="center").pack(side="left")
    ttk.Button(bar, text="+", width=3, command=lambda: zoom_by(1.25)).pack(side="left")
    ttk.Button(bar, text="Fit", width=5, command=lambda: render(fit)).pack(side="left", padx=(6, 0))
    ttk.Button(bar, text="100%", width=6, command=lambda: render(1.0)).pack(side="left", padx=(4, 18))

    ttk.Label(bar, text="Save as:").pack(side="left")
    name_var = tk.StringVar()
    missing = engine.missing_templates()
    names = catalog.picker_names(missing, engine.capturable_templates())
    if missing:
        name_var.set(missing[0])
    ttk.Combobox(bar, textvariable=name_var, values=names, width=28).pack(side="left", padx=6)

    def save():
        name = name_var.get().strip()
        if not sel["box"] or not name:
            messagebox.showwarning("Nothing to save", "Drag a box on the image and enter a name.", parent=top)
            return
        x1, y1, x2, y2 = [int(round(v)) for v in sel["box"]]
        crop = img[y1:y2, x1:x2]
        if crop.shape[0] < 8 or crop.shape[1] < 8:
            messagebox.showwarning("Too small", "The selected area is too small.", parent=top)
            return
        target = catalog.path(name)
        if target.exists() and not messagebox.askyesno(
                "Overwrite?", f"{name}.png already exists. Replace it?", parent=top):
            return
        if not catalog.save(name, crop):
            messagebox.showerror("Save failed", f"Could not write {target}", parent=top)
            return
        log_fn(f"Saved template: {name}.png ({crop.shape[1]}x{crop.shape[0]})")
        on_saved()
        sel["box"], sel["start"] = None, None
        draw_box()
        left = engine.missing_templates()
        name_var.set(left[0] if left else "")
        saved_var.set(f"Saved {name}.png ({crop.shape[1]}x{crop.shape[0]}). Select the next one.")

    def new_shot():
        nonlocal img, pil_full, h, w, fit
        try:
            game.focus()
            time.sleep(0.6)
            img = game.screenshot()
        except Exception as e:
            messagebox.showerror("Can't capture", str(e), parent=top)
            return
        h, w = img.shape[:2]
        pil_full = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        fit = max(MIN_Z, min(1.0, (win_w - 30) / w, (win_h - 110) / h))
        sel["box"], sel["start"] = None, None
        render(fit)
        top.lift()
        top.focus_force()
        saved_var.set("New screenshot taken.")

    ttk.Button(bar, text="Save", command=save).pack(side="left", padx=6)
    ttk.Button(bar, text="New screenshot", command=new_shot).pack(side="left", padx=(0, 6))
    ttk.Button(bar, text="Close", command=top.destroy).pack(side="left")
    saved_var = tk.StringVar()
    ttk.Label(bar, textvariable=saved_var, foreground="#1a7f1a").pack(side="left", padx=12)

    top.update_idletasks()
    render(fit)
