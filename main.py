import json
import threading
from datetime import datetime
from io import BytesIO
from pathlib import Path

import customtkinter as ctk
import requests
from PIL import Image

from scraper import fetch_stock, get_fruit_image_urls

CONFIG_FILE = Path(__file__).parent / "watchlist.json"

ALL_FRUITS = sorted([
    "Barrier", "Blade", "Blizzard", "Bomb", "Buddha", "Chop",
    "Control", "Dark", "Diamond", "Door", "Dough", "Dragon",
    "Flame", "Gas", "Gravity", "Ice", "Kilo", "Leopard",
    "Light", "Love", "Magma", "Mammoth", "Paw", "Phoenix",
    "Quake", "Revive", "Rubber", "Rumble", "Sand", "Shadow",
    "Shockwave", "Smoke", "Sound", "Spark", "Spider", "Spike",
    "Spin", "Spirit", "Spring", "String", "Venom",
])

IMG_SIZE = 32


class StockMonitorApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        self.title("Blox Fruits Stock Monitor")
        self.geometry("740x530")
        self.resizable(False, False)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self._watchlist: set[str] = set()
        self._current_stock: list[str] = []
        self._last_stock: list[str] = []
        self._before_stock: list[str] = []
        self._check_interval: int = 5
        self._timer: threading.Timer | None = None
        self._notified: set[str] = set()
        self._refresh_lock = threading.Lock()  # prevents concurrent refresh threads

        # image cache: fruit name -> CTkImage (loaded) or None (loading)
        self._image_cache: dict[str, ctk.CTkImage] = {}
        self._images_loading: set[str] = set()

        self._load_config()
        self._build_ui()
        self._start_polling()

    # ------------------------------------------------------------------ config

    def _load_config(self) -> None:
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                self._watchlist = set(data.get("watchlist", []))
                self._check_interval = int(data.get("interval", 5))
            except (json.JSONDecodeError, KeyError, ValueError):
                pass

    def _save_config(self) -> None:
        CONFIG_FILE.write_text(
            json.dumps(
                {"watchlist": sorted(self._watchlist), "interval": self._check_interval},
                indent=2,
            ),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------ image loading

    def _load_images_for(self, fruits: list[str]) -> None:
        """Trigger background loading for any fruit not yet cached or in-flight."""
        to_fetch = [
            f for f in fruits
            if f not in self._image_cache and f not in self._images_loading
        ]
        if not to_fetch:
            return
        self._images_loading.update(to_fetch)
        threading.Thread(target=self._batch_load_images, args=(to_fetch,), daemon=True).start()

    def _batch_load_images(self, fruits: list[str]) -> None:
        try:
            urls = get_fruit_image_urls(fruits)
        except Exception:
            self._images_loading.difference_update(fruits)
            return

        for fruit in fruits:
            url = urls.get(fruit)
            if url:
                try:
                    raw = requests.get(url, timeout=10).content
                    pil_img = (
                        Image.open(BytesIO(raw))
                        .convert("RGBA")
                        .resize((IMG_SIZE, IMG_SIZE), Image.LANCZOS)
                    )
                    self._image_cache[fruit] = ctk.CTkImage(pil_img, size=(IMG_SIZE, IMG_SIZE))
                except Exception:
                    pass
            self._images_loading.discard(fruit)

        self.after(0, self._redraw_panels)

    def _redraw_panels(self) -> None:
        self._refresh_stock_ui()
        self._refresh_watchlist_ui()

    # ------------------------------------------------------------------ UI build

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── Left: current stock ──────────────────────────────────────────────
        left = ctk.CTkFrame(self)
        left.grid(row=0, column=0, padx=(12, 6), pady=(12, 6), sticky="nsew")
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            left, text="Em Estoque Agora", font=ctk.CTkFont(size=15, weight="bold")
        ).grid(row=0, column=0, padx=12, pady=(12, 4), sticky="w")

        self._stock_frame = ctk.CTkScrollableFrame(left)
        self._stock_frame.grid(row=1, column=0, padx=8, pady=(0, 6), sticky="nsew")
        self._stock_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            left, text="Rotação Anterior", font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=2, column=0, padx=12, pady=(6, 2), sticky="w")
        self._last_label = ctk.CTkLabel(
            left, text="—", wraplength=295, justify="left",
            font=ctk.CTkFont(size=11), text_color="gray",
        )
        self._last_label.grid(row=3, column=0, padx=12, pady=(0, 4), sticky="w")

        ctk.CTkLabel(
            left, text="Antes da Anterior", font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=4, column=0, padx=12, pady=(4, 2), sticky="w")
        self._before_label = ctk.CTkLabel(
            left, text="—", wraplength=295, justify="left",
            font=ctk.CTkFont(size=11), text_color="gray",
        )
        self._before_label.grid(row=5, column=0, padx=12, pady=(0, 12), sticky="w")

        # ── Right: watchlist ─────────────────────────────────────────────────
        right = ctk.CTkFrame(self)
        right.grid(row=0, column=1, padx=(6, 12), pady=(12, 6), sticky="nsew")
        right.grid_rowconfigure(2, weight=1)
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            right, text="Alertas de Frutas", font=ctk.CTkFont(size=15, weight="bold")
        ).grid(row=0, column=0, padx=12, pady=(12, 6), sticky="w")

        add_frame = ctk.CTkFrame(right, fg_color="transparent")
        add_frame.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="ew")
        add_frame.grid_columnconfigure(0, weight=1)

        self._fruit_var = ctk.StringVar()
        self._combobox = ctk.CTkComboBox(
            add_frame, values=ALL_FRUITS, variable=self._fruit_var,
        )
        self._combobox.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self._combobox.bind("<Return>", lambda _e: self._add_fruit())

        ctk.CTkButton(
            add_frame, text="+ Add", width=72, command=self._add_fruit
        ).grid(row=0, column=1)

        self._watchlist_frame = ctk.CTkScrollableFrame(right)
        self._watchlist_frame.grid(row=2, column=0, padx=8, pady=(0, 12), sticky="nsew")
        self._watchlist_frame.grid_columnconfigure(0, weight=1)

        # ── Bottom bar ───────────────────────────────────────────────────────
        bottom = ctk.CTkFrame(self, height=46)
        bottom.grid(row=1, column=0, columnspan=2, padx=12, pady=(0, 10), sticky="ew")
        bottom.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(bottom, text="Atualizar a cada").grid(
            row=0, column=0, padx=(12, 4), pady=8
        )
        self._interval_var = ctk.StringVar(value=str(self._check_interval))
        ctk.CTkEntry(bottom, textvariable=self._interval_var, width=46).grid(
            row=0, column=1, padx=(0, 2), pady=8
        )
        ctk.CTkLabel(bottom, text="min").grid(row=0, column=2, padx=(0, 10), pady=8)

        ctk.CTkButton(
            bottom, text="Verificar Agora", width=130, command=self._check_now
        ).grid(row=0, column=3, padx=6, pady=8, sticky="e")

        self._status_label = ctk.CTkLabel(
            bottom, text="Aguardando...", text_color="gray",
            font=ctk.CTkFont(size=11),
        )
        self._status_label.grid(row=0, column=4, padx=12, pady=8)

        self._refresh_watchlist_ui()

    # ------------------------------------------------------------------ fruit row helpers

    def _make_fruit_row(
        self,
        parent: ctk.CTkScrollableFrame,
        fruit: str,
        *,
        highlighted: bool,
        badge: str = "",
        color: str = "white",
        font_weight: str = "normal",
        extra_widget_fn=None,
    ) -> None:
        """Render a single fruit row with icon + name inside `parent`."""
        bg = "#1a3a2a" if highlighted else "#2b2b2b"
        row = ctk.CTkFrame(parent, fg_color=bg, corner_radius=6)
        row.pack(fill="x", padx=4, pady=2)
        row.grid_columnconfigure(1, weight=1)

        # ── icon / image ────────────────────────────────
        img = self._image_cache.get(fruit)
        img_label = ctk.CTkLabel(
            row,
            image=img,
            text="",
            width=IMG_SIZE + 4,
            height=IMG_SIZE + 4,
        )
        img_label.grid(row=0, column=0, padx=(6, 2), pady=6)

        # ── name + badge ────────────────────────────────
        text = f"{badge}  {fruit}" if badge else fruit
        ctk.CTkLabel(
            row,
            text=text,
            font=ctk.CTkFont(size=13, weight=font_weight),
            text_color=color,
            anchor="w",
        ).grid(row=0, column=1, sticky="ew", padx=(2, 6), pady=6)

        # ── optional extra widget (e.g. remove button) ──
        if extra_widget_fn:
            extra_widget_fn(row, 2)

    # ------------------------------------------------------------------ UI refresh

    def _refresh_stock_ui(self) -> None:
        for w in self._stock_frame.winfo_children():
            w.destroy()

        if not self._current_stock:
            ctk.CTkLabel(
                self._stock_frame, text="Nenhuma fruta em estoque", text_color="gray"
            ).pack(pady=12)
            return

        self._load_images_for(self._current_stock)

        for fruit in self._current_stock:
            watched = fruit in self._watchlist
            self._make_fruit_row(
                self._stock_frame,
                fruit,
                highlighted=watched,
                badge="🔔" if watched else "",
                color="#2ecc71" if watched else "white",
                font_weight="bold" if watched else "normal",
            )

    def _refresh_watchlist_ui(self) -> None:
        for w in self._watchlist_frame.winfo_children():
            w.destroy()

        if not self._watchlist:
            ctk.CTkLabel(
                self._watchlist_frame,
                text="Adicione frutas para receber\nalertas quando entrarem em stock.",
                text_color="gray",
                justify="center",
            ).pack(pady=16)
            return

        fruits = sorted(self._watchlist)
        self._load_images_for(fruits)

        for fruit in fruits:
            in_stock = fruit in self._current_stock

            def remove_btn(parent: ctk.CTkFrame, col: int, _fruit: str = fruit) -> None:
                ctk.CTkButton(
                    parent,
                    text="✕",
                    width=28,
                    height=24,
                    fg_color="transparent",
                    hover_color="#7f1d1d",
                    command=lambda f=_fruit: self._remove_fruit(f),
                ).grid(row=0, column=col, padx=6)

            self._make_fruit_row(
                self._watchlist_frame,
                fruit,
                highlighted=in_stock,
                badge="✓" if in_stock else "",
                color="#2ecc71" if in_stock else "white",
                font_weight="bold" if in_stock else "normal",
                extra_widget_fn=remove_btn,
            )

    # ------------------------------------------------------------------ watchlist actions

    def _add_fruit(self) -> None:
        fruit = self._fruit_var.get().strip().title()
        if fruit and fruit not in self._watchlist:
            self._watchlist.add(fruit)
            self._save_config()
            self._load_images_for([fruit])
            self._refresh_watchlist_ui()
            self._refresh_stock_ui()
        self._fruit_var.set("")
        self._combobox.set("")

    def _remove_fruit(self, fruit: str) -> None:
        self._watchlist.discard(fruit)
        self._notified.discard(fruit)
        self._save_config()
        self._refresh_watchlist_ui()
        self._refresh_stock_ui()

    # ------------------------------------------------------------------ polling

    def _check_now(self) -> None:
        try:
            self._check_interval = max(1, int(self._interval_var.get()))
        except ValueError:
            self._interval_var.set(str(self._check_interval))
        self._save_config()
        threading.Thread(target=self._refresh, daemon=True).start()
        self._schedule_next()

    def _refresh(self) -> None:
        if not self._refresh_lock.acquire(blocking=False):
            return  # a refresh is already running; skip this one
        self.after(0, lambda: self._status_label.configure(
            text="Verificando...", text_color="#f39c12"
        ))
        try:
            stock = fetch_stock()
            self._current_stock = stock.get("Current", [])
            self._last_stock = stock.get("Last", [])
            self._before_stock = stock.get("Before", [])
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.after(0, self._apply_refresh, timestamp)
            self._fire_alerts()
        except Exception as exc:
            self.after(0, lambda: self._status_label.configure(
                text=f"Erro: {exc}", text_color="#e74c3c"
            ))
        finally:
            self._refresh_lock.release()

    def _apply_refresh(self, timestamp: str) -> None:
        self._refresh_stock_ui()
        self._refresh_watchlist_ui()
        self._last_label.configure(
            text=", ".join(self._last_stock) if self._last_stock else "—"
        )
        self._before_label.configure(
            text=", ".join(self._before_stock) if self._before_stock else "—"
        )
        self._status_label.configure(
            text=f"Atualizado às {timestamp}  •  próximo em {self._check_interval} min",
            text_color="#2ecc71",
        )

    def _schedule_next(self) -> None:
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(self._check_interval * 60, self._poll_tick)
        self._timer.daemon = True
        self._timer.start()

    def _poll_tick(self) -> None:
        threading.Thread(target=self._refresh, daemon=True).start()
        self._schedule_next()

    def _start_polling(self) -> None:
        threading.Thread(target=self._refresh, daemon=True).start()
        self._schedule_next()

    # ------------------------------------------------------------------ notifications

    def _fire_alerts(self) -> None:
        # Take snapshots to avoid iterating shared state from a background thread
        watchlist = frozenset(self._watchlist)
        current = frozenset(self._current_stock)
        for fruit in watchlist:
            if fruit in current and fruit not in self._notified:
                self._notified.add(fruit)
                self._notify(fruit)
            elif fruit not in current:
                self._notified.discard(fruit)

    def _notify(self, fruit: str) -> None:
        try:
            from plyer import notification
            notification.notify(
                title="Blox Fruits — Fruta em Stock!",
                message=f"{fruit} está disponível agora!",
                app_name="Blox Fruits Monitor",
                timeout=8,
            )
        except Exception:
            pass

    # ------------------------------------------------------------------ cleanup

    def destroy(self) -> None:
        if self._timer:
            self._timer.cancel()
        super().destroy()


def main() -> None:
    app = StockMonitorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
