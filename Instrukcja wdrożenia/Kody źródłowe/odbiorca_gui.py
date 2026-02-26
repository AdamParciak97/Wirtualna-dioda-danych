#!/usr/bin/env python3
"""
Dioda - Aplikacja Odbiorcy
GUI do odbierania plików przez wirtualną diodę danych
Windows A → Dioda (Oracle Linux 8) → Windows B
"""

import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import threading
import os
import time
import hashlib
import winsound
from datetime import datetime
from pathlib import Path

# ─── KONFIGURACJA ────────────────────────────────────────────────────────────
UFTPD_EXE = r"C:\uftp\uftpd.exe"
INTERFEJS = "192.168.20.1"
KATALOG_ODR = r"C:\odebrane"

# ─── KOLORY ──────────────────────────────────────────────────────────────────
KOL_TLO = "#0d1117"
KOL_PANEL = "#161b22"
KOL_AKCENT = "#1c2333"
KOL_PODSWIETL = "#58a6ff"
KOL_SUKCES = "#3fb950"
KOL_OSTRZEZENIE = "#d29922"
KOL_BLAD = "#f85149"
KOL_TEKST = "#c9d1d9"
KOL_TEKST_DIM = "#6e7681"
KOL_RAMKA = "#30363d"


def oblicz_sha256(sciezka: str) -> str:
    sha = hashlib.sha256()
    with open(sciezka, "rb") as f:
        for blok in iter(lambda: f.read(65536), b""):
            sha.update(blok)
    return sha.hexdigest()


class OdbiorcaApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("DIODA – Odbiorca")
        self.geometry("860x680")
        self.resizable(False, False)
        self.configure(bg=KOL_TLO)

        # Stan aplikacji
        self.nasluchiwanie = False
        self.odebrane_pliki = []
        self.uftpd_proces = None
        self.znane_pliki = set()
        self.powiadomienia = tk.BooleanVar(value=True)

        # Upewnij się że katalog odbioru istnieje
        os.makedirs(KATALOG_ODR, exist_ok=True)

        # Zapamiętaj pliki które już istniały przed uruchomieniem
        self.znane_pliki = set(os.listdir(KATALOG_ODR))

        self._buduj_ui()
        self._monitoruj_katalog()

        # Autostart nasłuchu przy uruchomieniu aplikacji
        self.after(1000, self._start_nasluch)

    # ─── BUDOWANIE UI ────────────────────────────────────────────────────────
    def _buduj_ui(self):
        # ── Nagłówek ──
        naglowek = tk.Frame(self, bg=KOL_AKCENT, height=70)
        naglowek.pack(fill="x")
        naglowek.pack_propagate(False)

        tk.Label(
            naglowek,
            text="⬡ SYSTEM DIODA",
            font=("Courier New", 18, "bold"),
            bg=KOL_AKCENT,
            fg=KOL_PODSWIETL
        ).pack(side="left", padx=20, pady=15)

        tk.Label(
            naglowek,
            text="ODBIORCA // 192.168.20.1",
            font=("Courier New", 10),
            bg=KOL_AKCENT,
            fg=KOL_TEKST_DIM
        ).pack(side="left", padx=10)

        # Status nasłuchiwania
        self.lbl_status_nasl = tk.Label(
            naglowek,
            text="● ZATRZYMANY",
            font=("Courier New", 10, "bold"),
            bg=KOL_AKCENT,
            fg=KOL_BLAD
        )
        self.lbl_status_nasl.pack(side="right", padx=20)

        # ── Pasek sterowania ──
        sterowanie = tk.Frame(self, bg=KOL_PANEL, height=55)
        sterowanie.pack(fill="x")
        sterowanie.pack_propagate(False)

        self.btn_start = tk.Button(
            sterowanie,
            text="▶ URUCHOM NASŁUCH",
            font=("Courier New", 10, "bold"),
            bg=KOL_SUKCES,
            fg="white",
            relief="flat",
            cursor="hand2",
            activebackground="#2ea043",
            activeforeground="white",
            command=self._toggle_nasluch
        )
        self.btn_start.pack(side="left", padx=15, pady=10, ipady=6, ipadx=12)

        # Checkbox powiadomień dźwiękowych
        tk.Checkbutton(
            sterowanie,
            text="Dźwięk przy odbiorze",
            variable=self.powiadomienia,
            font=("Courier New", 9),
            bg=KOL_PANEL,
            fg=KOL_TEKST_DIM,
            selectcolor=KOL_AKCENT,
            activebackground=KOL_PANEL,
            activeforeground=KOL_TEKST
        ).pack(side="left", padx=10)

        # Licznik
        self.lbl_licznik = tk.Label(
            sterowanie,
            text="Odebrano: 0 plików",
            font=("Courier New", 9),
            bg=KOL_PANEL,
            fg=KOL_TEKST_DIM
        )
        self.lbl_licznik.pack(side="right", padx=15)

        # ── Pasek postępu odbioru ──
        postep_ramka = tk.Frame(self, bg=KOL_TLO)
        postep_ramka.pack(fill="x", padx=20, pady=(12, 0))

        tk.Label(
            postep_ramka,
            text="▸ POSTĘP ODBIORU",
            font=("Courier New", 10, "bold"),
            bg=KOL_TLO,
            fg=KOL_PODSWIETL
        ).pack(anchor="w", pady=(0, 6))

        postep_panel = tk.Frame(postep_ramka, bg=KOL_PANEL)
        postep_panel.pack(fill="x")

        tk.Frame(postep_panel, bg=KOL_RAMKA, height=2).pack(fill="x")

        postep_wnetrze = tk.Frame(postep_panel, bg=KOL_PANEL)
        postep_wnetrze.pack(fill="x", padx=12, pady=10)

        self.lbl_aktualny = tk.Label(
            postep_wnetrze,
            text="Oczekiwanie na pliki...",
            font=("Courier New", 9),
            bg=KOL_PANEL,
            fg=KOL_TEKST_DIM
        )
        self.lbl_aktualny.pack(anchor="w", pady=(0, 6))

        styl = ttk.Style()
        styl.theme_use("default")
        styl.configure(
            "Odbiorca.Horizontal.TProgressbar",
            troughcolor=KOL_AKCENT,
            background=KOL_PODSWIETL,
            bordercolor=KOL_AKCENT,
            lightcolor=KOL_PODSWIETL,
            darkcolor=KOL_PODSWIETL,
            thickness=16
        )

        self.pasek_postepu = ttk.Progressbar(
            postep_wnetrze,
            style="Odbiorca.Horizontal.TProgressbar",
            orient="horizontal",
            mode="indeterminate"
        )
        self.pasek_postepu.pack(fill="x")

        # ── Lista odebranych plików ──
        lista_ramka = tk.Frame(self, bg=KOL_TLO)
        lista_ramka.pack(fill="both", expand=True, padx=20, pady=12)

        nagl_lista = tk.Frame(lista_ramka, bg=KOL_TLO)
        nagl_lista.pack(fill="x", pady=(0, 6))

        tk.Label(
            nagl_lista,
            text="▸ ODEBRANE PLIKI",
            font=("Courier New", 10, "bold"),
            bg=KOL_TLO,
            fg=KOL_PODSWIETL
        ).pack(side="left")

        tk.Label(
            nagl_lista,
            text=f"Katalog: {KATALOG_ODR}",
            font=("Courier New", 8),
            bg=KOL_TLO,
            fg=KOL_TEKST_DIM
        ).pack(side="right")

        # Nagłówki tabeli
        naglowki = tk.Frame(lista_ramka, bg=KOL_AKCENT)
        naglowki.pack(fill="x")

        for tekst, szer in [
            ("CZAS", 90),
            ("NAZWA PLIKU", 320),
            ("ROZMIAR", 90),
            ("SHA256", 200),
            ("STATUS", 80)
        ]:
            tk.Label(
                naglowki,
                text=tekst,
                font=("Courier New", 8, "bold"),
                bg=KOL_AKCENT,
                fg=KOL_TEKST_DIM,
                width=szer // 8,
                anchor="w"
            ).pack(side="left", padx=8, pady=5)

        # Lista z przewijaniem
        lista_panel = tk.Frame(lista_ramka, bg=KOL_PANEL)
        lista_panel.pack(fill="both", expand=True)

        tk.Frame(lista_panel, bg=KOL_RAMKA, height=2).pack(fill="x")

        scroll_y = tk.Scrollbar(lista_panel, bg=KOL_PANEL, troughcolor=KOL_PANEL)
        scroll_y.pack(side="right", fill="y")

        scroll_x = tk.Scrollbar(
            lista_panel,
            bg=KOL_PANEL,
            troughcolor=KOL_PANEL,
            orient="horizontal"
        )
        scroll_x.pack(side="bottom", fill="x")

        self.lista = tk.Listbox(
            lista_panel,
            font=("Courier New", 9),
            bg=KOL_PANEL,
            fg=KOL_TEKST,
            selectbackground=KOL_AKCENT,
            selectforeground=KOL_TEKST,
            relief="flat",
            bd=0,
            yscrollcommand=scroll_y.set,
            xscrollcommand=scroll_x.set,
            activestyle="none"
        )
        self.lista.pack(fill="both", expand=True, padx=4, pady=4)

        scroll_y.config(command=self.lista.yview)
        scroll_x.config(command=self.lista.xview)

        # Podwójne kliknięcie → otwórz folder
        self.lista.bind("<Double-Button-1>", self._otworz_folder)

        # ── Pasek statusu ──
        pasek = tk.Frame(self, bg=KOL_AKCENT, height=30)
        pasek.pack(fill="x", side="bottom")
        pasek.pack_propagate(False)

        self.lbl_status = tk.Label(
            pasek,
            text="Gotowy. Uruchom nasłuch aby odbierać pliki.",
            font=("Courier New", 9),
            bg=KOL_AKCENT,
            fg=KOL_TEKST_DIM
        )
        self.lbl_status.pack(side="left", padx=15, pady=6)

        tk.Label(
            pasek,
            text=f"Katalog: {KATALOG_ODR} | Port: 1044/UDP",
            font=("Courier New", 9),
            bg=KOL_AKCENT,
            fg=KOL_TEKST_DIM
        ).pack(side="right", padx=15)

    # ─── LOGIKA ──────────────────────────────────────────────────────────────
    def _toggle_nasluch(self):
        if not self.nasluchiwanie:
            self._start_nasluch()
        else:
            self._stop_nasluch()

    def _start_nasluch(self):
        try:
            cmd = [UFTPD_EXE, "-D", KATALOG_ODR, "-I", INTERFEJS]
            self.uftpd_proces = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            self.nasluchiwanie = True
            self.btn_start.config(
                text="■ ZATRZYMAJ NASŁUCH",
                bg=KOL_BLAD,
                activebackground="#c9302c"
            )
            self.lbl_status_nasl.config(
                text="● NASŁUCHUJE",
                fg=KOL_SUKCES
            )
            self.lbl_status.config(
                text=f"Nasłuchuję na {INTERFEJS}:1044 – oczekuję na pliki..."
            )
            self.pasek_postepu.start(15)
            self.lbl_aktualny.config(
                text="Nasłuchuję... oczekiwanie na pliki z diody.",
                fg=KOL_TEKST
            )

            # Wątek pilnujący że uftpd żyje – auto-restart
            threading.Thread(
                target=self._pilnuj_procesu,
                daemon=True
            ).start()

        except FileNotFoundError:
            messagebox.showerror(
                "Błąd",
                f"Nie znaleziono uftpd.exe!\nSprawdź ścieżkę: {UFTPD_EXE}"
            )

    def _pilnuj_procesu(self):
        """Monitoruje proces uftpd i restartuje go jeśli padnie."""
        while self.nasluchiwanie:
            if self.uftpd_proces and self.uftpd_proces.poll() is not None:
                # Proces zakończył się nieoczekiwanie
                self.lbl_status_nasl.config(
                    text="● RESTART...",
                    fg=KOL_OSTRZEZENIE
                )
                self.lbl_status.config(
                    text="uftpd zakończył się nieoczekiwanie – restartuję..."
                )
                time.sleep(2)

                if self.nasluchiwanie:  # upewnij się że użytkownik nie zatrzymał
                    try:
                        cmd = [UFTPD_EXE, "-D", KATALOG_ODR, "-I", INTERFEJS]
                        self.uftpd_proces = subprocess.Popen(
                            cmd,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                        self.lbl_status_nasl.config(
                            text="● NASŁUCHUJE",
                            fg=KOL_SUKCES
                        )
                        self.lbl_status.config(
                            text=f"uftpd zrestartowany – nasłuchuję na {INTERFEJS}:1044"
                        )
                    except Exception as e:
                        self.lbl_status.config(
                            text=f"Błąd restartu uftpd: {e}"
                        )

            time.sleep(3)

    def _stop_nasluch(self):
        if self.uftpd_proces:
            self.uftpd_proces.terminate()
            self.uftpd_proces = None

        self.nasluchiwanie = False
        self.btn_start.config(
            text="▶ URUCHOM NASŁUCH",
            bg=KOL_SUKCES,
            activebackground="#2ea043"
        )
        self.lbl_status_nasl.config(text="● ZATRZYMANY", fg=KOL_BLAD)
        self.lbl_status.config(text="Nasłuch zatrzymany.")
        self.pasek_postepu.stop()
        self.lbl_aktualny.config(
            text="Nasłuch zatrzymany.",
            fg=KOL_TEKST_DIM
        )

    def _monitoruj_katalog(self):
        """Monitoruje katalog odbioru i reaguje na nowe pliki."""
        def petla():
            while True:
                try:
                    if os.path.exists(KATALOG_ODR):
                        aktualne = set(os.listdir(KATALOG_ODR))
                        nowe = aktualne - self.znane_pliki

                        for plik in nowe:
                            # Pomiń pliki SHA256
                            if plik.endswith(".sha256"):
                                self.znane_pliki.add(plik)
                                continue

                            sciezka = os.path.join(KATALOG_ODR, plik)

                            # Poczekaj aż plik się w pełni zapisze
                            time.sleep(1)

                            self._nowy_plik(plik, sciezka)
                            self.znane_pliki.add(plik)

                except Exception:
                    pass

                time.sleep(2)

        threading.Thread(target=petla, daemon=True).start()

    def _nowy_plik(self, nazwa: str, sciezka: str):
        """Obsługuje nowo odebrany plik."""
        znacznik = datetime.now().strftime("%H:%M:%S")
        rozmiar = self._formatuj_rozmiar(os.path.getsize(sciezka))

        # Oblicz SHA256
        self.lbl_aktualny.config(
            text=f"Weryfikuję: {nazwa}",
            fg=KOL_OSTRZEZENIE
        )

        try:
            sha = oblicz_sha256(sciezka)
            sha_skrot = sha[:16] + "..."
            status = "✓ OK"
            kolor = KOL_SUKCES
        except Exception:
            sha_skrot = "błąd"
            status = "✗ BŁĄD"
            kolor = KOL_BLAD

        # Dodaj do listy
        wpis = f" {znacznik} {nazwa:<35} {rozmiar:<10} {sha_skrot:<20} {status}"
        self.lista.insert(0, wpis)
        self.lista.itemconfig(0, fg=kolor)

        # Aktualizuj licznik
        self.odebrane_pliki.append(nazwa)
        self.lbl_licznik.config(
            text=f"Odebrano: {len(self.odebrane_pliki)} plików"
        )

        self.lbl_aktualny.config(
            text=f"✓ Ostatni odebrany: {nazwa} ({rozmiar})",
            fg=KOL_SUKCES
        )
        self.lbl_status.config(
            text=f"Odebrано: {nazwa} o {znacznik}"
        )

        # Powiadomienie dźwiękowe
        if self.powiadomienia.get():
            try:
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass

        # Powiadomienie okienkowe (nie blokujące)
        self._pokaz_powiadomienie(nazwa, rozmiar, znacznik)

    def _pokaz_powiadomienie(self, nazwa: str, rozmiar: str, czas: str):
        """Wyświetla nieinwazyjne powiadomienie o nowym pliku."""
        okno = tk.Toplevel(self)
        okno.title("Nowy plik!")
        okno.geometry("380x130")
        okno.resizable(False, False)
        okno.configure(bg=KOL_PANEL)
        okno.attributes("-topmost", True)

        # Pozycja w prawym dolnym rogu
        x = self.winfo_screenwidth() - 400
        y = self.winfo_screenheight() - 180
        okno.geometry(f"+{x}+{y}")

        tk.Label(
            okno,
            text=" NOWY PLIK ODEBRANY",
            font=("Courier New", 11, "bold"),
            bg=KOL_PANEL,
            fg=KOL_SUKCES
        ).pack(pady=(12, 4))

        tk.Label(
            okno,
            text=f"{nazwa}",
            font=("Courier New", 10),
            bg=KOL_PANEL,
            fg=KOL_TEKST
        ).pack()

        tk.Label(
            okno,
            text=f"Rozmiar: {rozmiar} | Czas: {czas}",
            font=("Courier New", 8),
            bg=KOL_PANEL,
            fg=KOL_TEKST_DIM
        ).pack(pady=4)

        tk.Button(
            okno,
            text="OK",
            font=("Courier New", 9, "bold"),
            bg=KOL_PODSWIETL,
            fg="white",
            relief="flat",
            cursor="hand2",
            command=okno.destroy
        ).pack(pady=(4, 0), ipadx=20, ipady=4)

        # Zamknij automatycznie po 5 sekundach
        okno.after(5000, lambda: okno.destroy() if okno.winfo_exists() else None)

    def _otworz_folder(self, event):
        """Podwójne kliknięcie otwiera folder z plikami."""
        os.startfile(KATALOG_ODR)

    @staticmethod
    def _formatuj_rozmiar(bajty: int) -> str:
        for jednostka in ["B", "KB", "MB", "GB"]:
            if bajty < 1024:
                return f"{bajty:.1f} {jednostka}"
            bajty /= 1024
        return f"{bajty:.1f} TB"

    def on_zamknij(self):
        self._stop_nasluch()
        self.destroy()


if __name__ == "__main__":
    app = OdbiorcaApp()
    app.protocol("WM_DELETE_WINDOW", app.on_zamknij)
    app.mainloop()