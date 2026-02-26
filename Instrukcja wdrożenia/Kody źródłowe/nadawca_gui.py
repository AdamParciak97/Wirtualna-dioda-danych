#!/usr/bin/env python3
"""
Dioda - Aplikacja Nadawcy
GUI do wysyłania plików przez wirtualną diodę danych
Windows A -> Dioda (Oracle Linux 8) -> Windows B
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import subprocess
import threading
import hashlib
import os
import socket
import time
import traceback
from datetime import datetime

# ─── KONFIGURACJA ────────────────────────────────────────────────────────────
UFTP_EXE = r"C:\uftp\uftp.exe"
INTERFEJS = "192.168.10.1"
IP_DIODY = "192.168.10.254"
PORT_DIODY = 1044
PREDKOSC = "50000"
POWTORZENIA = "3"

# Uwaga:
# Wcześniej było "-Y aes256-cbc", ale u Ciebie pojawiał się błąd "Invalid keytype".
# Dlatego domyślnie wyłączone. Można wrócić po potwierdzeniu poprawnej składni
# dla konkretnej wersji uftp.exe.
UFTP_UZYJ_SZYFROWANIA = False
UFTP_CIPHER = "aes256-cbc"   # tylko informacyjnie / do przyszłego użycia
UFTP_HASH = "sha256"

# ─── KOLORY ──────────────────────────────────────────────────────────────────
KOL_TLO = "#1a1a2e"
KOL_PANEL = "#16213e"
KOL_AKCENT = "#0f3460"
KOL_PODSWIETL = "#e94560"
KOL_SUKCES = "#00b894"
KOL_OSTRZEZENIE = "#fdcb6e"
KOL_TEKST = "#eaeaea"
KOL_TEKST_DIM = "#8892a4"
KOL_RAMKA = "#0f3460"

# ─── FUNKCJE POMOCNICZE ──────────────────────────────────────────────────────
def oblicz_sha256(sciezka: str) -> str:
    sha = hashlib.sha256()
    with open(sciezka, "rb") as f:
        for blok in iter(lambda: f.read(65536), b""):
            sha.update(blok)
    return sha.hexdigest()


def sprawdz_polaczenie() -> bool:
    """
    Bardziej sensowny test "czy host diody żyje" niż sam TCP/22.
    Najpierw ping, potem fallback na TCP/22.
    """
    try:
        wynik = subprocess.run(
            ["ping", "-n", "1", "-w", "1000", IP_DIODY],
            capture_output=True,
            text=True
        )
        if wynik.returncode == 0:
            return True
    except Exception:
        pass

    # Fallback: SSH/TCP22 (jeśli jest włączone)
    try:
        sock = socket.create_connection((IP_DIODY, 22), timeout=2)
        sock.close()
        return True
    except Exception:
        return False


class NadawcaApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("DIODA – Nadawca")
        self.geometry("820x650")
        self.resizable(False, False)
        self.configure(bg=KOL_TLO)

        # Stan aplikacji
        self.wybrany_plik = tk.StringVar(value="Nie wybrano pliku")
        self.status_txt = tk.StringVar(value="Gotowy")
        self.polaczenie_ok = False
        self.historia = []
        self.wysylanie = False
        self.sha256 = None
        self.sciezka_pliku = None

        self._buduj_ui()
        self._sprawdzaj_polaczenie()

    # ─── HELPERY UI (thread-safe) ────────────────────────────────────────────
    def _ui(self, fn, *args, **kwargs):
        """Wykonaj operację UI w głównym wątku Tkinter."""
        self.after(0, lambda: fn(*args, **kwargs))

    def _set_btn_wyslij_enabled(self, enabled: bool):
        if enabled:
            self.btn_wyslij.config(state="normal")
        else:
            self.btn_wyslij.config(state="disabled")

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
            text=f"NADAWCA // {INTERFEJS}",
            font=("Courier New", 10),
            bg=KOL_AKCENT,
            fg=KOL_TEKST_DIM
        ).pack(side="left", padx=10, pady=15)

        # Wskaźnik połączenia (host reachable, nie stricte UFTP)
        self.lbl_polaczenie = tk.Label(
            naglowek,
            text="● SPRAWDZANIE...",
            font=("Courier New", 10, "bold"),
            bg=KOL_AKCENT,
            fg=KOL_OSTRZEZENIE
        )
        self.lbl_polaczenie.pack(side="right", padx=20)

        # ── Główna zawartość ──
        glowny = tk.Frame(self, bg=KOL_TLO)
        glowny.pack(fill="both", expand=True, padx=20, pady=15)

        # Lewa kolumna
        lewa = tk.Frame(glowny, bg=KOL_TLO)
        lewa.pack(side="left", fill="both", expand=True, padx=(0, 10))

        self._buduj_sekcje_pliku(lewa)
        self._buduj_sekcje_opcji(lewa)
        self._buduj_sekcje_postepu(lewa)

        # Prawa kolumna – historia
        prawa = tk.Frame(glowny, bg=KOL_TLO, width=280)
        prawa.pack(side="right", fill="both")
        prawa.pack_propagate(False)

        self._buduj_sekcje_historii(prawa)

        # ── Pasek statusu ──
        pasek = tk.Frame(self, bg=KOL_AKCENT, height=30)
        pasek.pack(fill="x", side="bottom")
        pasek.pack_propagate(False)

        tk.Label(
            pasek,
            textvariable=self.status_txt,
            font=("Courier New", 9),
            bg=KOL_AKCENT,
            fg=KOL_TEKST_DIM
        ).pack(side="left", padx=15, pady=6)

        tk.Label(
            pasek,
            text=f"Dioda: {IP_DIODY}:{PORT_DIODY}",
            font=("Courier New", 9),
            bg=KOL_AKCENT,
            fg=KOL_TEKST_DIM
        ).pack(side="right", padx=15)

    def _ramka(self, rodzic, tytul):
        """Tworzy sekcję z tytułem."""
        opak = tk.Frame(rodzic, bg=KOL_TLO)
        opak.pack(fill="x", pady=(0, 12))

        tk.Label(
            opak,
            text=f"▸ {tytul}",
            font=("Courier New", 10, "bold"),
            bg=KOL_TLO,
            fg=KOL_PODSWIETL
        ).pack(anchor="w", pady=(0, 6))

        zawartosc = tk.Frame(opak, bg=KOL_PANEL, relief="flat", bd=0)
        zawartosc.pack(fill="x")

        tk.Frame(zawartosc, bg=KOL_RAMKA, height=2).pack(fill="x")

        wnetrze = tk.Frame(zawartosc, bg=KOL_PANEL)
        wnetrze.pack(fill="x", padx=12, pady=10)
        return wnetrze

    def _buduj_sekcje_pliku(self, rodzic):
        w = self._ramka(rodzic, "WYBÓR PLIKU")

        # Ścieżka pliku
        tk.Label(
            w, text="Ścieżka:", font=("Courier New", 9),
            bg=KOL_PANEL, fg=KOL_TEKST_DIM
        ).pack(anchor="w")

        wiersz = tk.Frame(w, bg=KOL_PANEL)
        wiersz.pack(fill="x", pady=(3, 8))

        self.lbl_plik = tk.Label(
            wiersz,
            textvariable=self.wybrany_plik,
            font=("Courier New", 9),
            bg=KOL_AKCENT,
            fg=KOL_TEKST,
            anchor="w",
            width=38,
            relief="flat"
        )
        self.lbl_plik.pack(side="left", fill="x", expand=True, ipady=5, ipadx=5)

        tk.Button(
            wiersz,
            text="PRZEGLĄDAJ",
            font=("Courier New", 9, "bold"),
            bg=KOL_PODSWIETL,
            fg="white",
            relief="flat",
            cursor="hand2",
            activebackground="#c73652",
            activeforeground="white",
            command=self._wybierz_plik
        ).pack(side="right", padx=(8, 0), ipady=5, ipadx=8)

        # Info o pliku
        self.lbl_info_plik = tk.Label(
            w,
            text="",
            font=("Courier New", 9),
            bg=KOL_PANEL,
            fg=KOL_TEKST_DIM
        )
        self.lbl_info_plik.pack(anchor="w")

        # SHA256
        self.lbl_sha = tk.Label(
            w,
            text="",
            font=("Courier New", 8),
            bg=KOL_PANEL,
            fg=KOL_TEKST_DIM,
            wraplength=380,
            justify="left"
        )
        self.lbl_sha.pack(anchor="w", pady=(4, 0))

        # Przycisk WYŚLIJ
        self.btn_wyslij = tk.Button(
            w,
            text="▶ WYŚLIJ PRZEZ DIODĘ",
            font=("Courier New", 11, "bold"),
            bg=KOL_SUKCES,
            fg="white",
            relief="flat",
            cursor="hand2",
            activebackground="#00a381",
            activeforeground="white",
            state="disabled",
            command=self._wyslij
        )
        self.btn_wyslij.pack(fill="x", pady=(10, 0), ipady=10)

    def _buduj_sekcje_opcji(self, rodzic):
        w = self._ramka(rodzic, "PARAMETRY TRANSFERU")

        siatka = tk.Frame(w, bg=KOL_PANEL)
        siatka.pack(fill="x")

        def pole(rodzic_s, etykieta, wartosc, kolumna):
            tk.Label(
                rodzic_s, text=etykieta, font=("Courier New", 8),
                bg=KOL_PANEL, fg=KOL_TEKST_DIM
            ).grid(row=0, column=kolumna, sticky="w", padx=(0, 15))

            tk.Label(
                rodzic_s, text=wartosc, font=("Courier New", 9, "bold"),
                bg=KOL_PANEL, fg=KOL_TEKST
            ).grid(row=1, column=kolumna, sticky="w", padx=(0, 15))

        pole(siatka, "Interfejs", INTERFEJS, 0)
        pole(siatka, "Prędkość", f"{PREDKOSC} Kbps", 1)
        pole(siatka, "Powtórzenia", POWTORZENIA, 2)
        pole(siatka, "Szyfrowanie", "WYŁĄCZONE" if not UFTP_UZYJ_SZYFROWANIA else UFTP_CIPHER.upper(), 3)

    def _buduj_sekcje_postepu(self, rodzic):
        w = self._ramka(rodzic, "POSTĘP WYSYŁKI")

        self.lbl_postep_txt = tk.Label(
            w, text="Oczekiwanie...",
            font=("Courier New", 9),
            bg=KOL_PANEL, fg=KOL_TEKST_DIM
        )
        self.lbl_postep_txt.pack(anchor="w", pady=(0, 6))

        # Pasek postępu
        styl = ttk.Style()
        styl.theme_use("default")
        styl.configure(
            "Dioda.Horizontal.TProgressbar",
            troughcolor=KOL_AKCENT,
            background=KOL_SUKCES,
            bordercolor=KOL_AKCENT,
            lightcolor=KOL_SUKCES,
            darkcolor=KOL_SUKCES,
            thickness=18
        )

        self.pasek_postepu = ttk.Progressbar(
            w,
            style="Dioda.Horizontal.TProgressbar",
            orient="horizontal",
            length=400,
            mode="determinate"
        )
        self.pasek_postepu.pack(fill="x", pady=(0, 6))

        self.lbl_procent = tk.Label(
            w, text="0%",
            font=("Courier New", 10, "bold"),
            bg=KOL_PANEL, fg=KOL_SUKCES
        )
        self.lbl_procent.pack(anchor="e")

    def _buduj_sekcje_historii(self, rodzic):
        tk.Label(
            rodzic,
            text="▸ HISTORIA WYSYŁEK",
            font=("Courier New", 10, "bold"),
            bg=KOL_TLO,
            fg=KOL_PODSWIETL
        ).pack(anchor="w", pady=(0, 6))

        ramka = tk.Frame(rodzic, bg=KOL_PANEL)
        ramka.pack(fill="both", expand=True)

        tk.Frame(ramka, bg=KOL_RAMKA, height=2).pack(fill="x")

        # Lista z przewijaniem
        scroll = tk.Scrollbar(ramka, bg=KOL_PANEL)
        scroll.pack(side="right", fill="y")

        self.lista_historia = tk.Listbox(
            ramka,
            font=("Courier New", 8),
            bg=KOL_PANEL,
            fg=KOL_TEKST,
            selectbackground=KOL_AKCENT,
            selectforeground=KOL_TEKST,
            relief="flat",
            bd=0,
            yscrollcommand=scroll.set,
            activestyle="none"
        )
        self.lista_historia.pack(fill="both", expand=True, padx=8, pady=8)
        scroll.config(command=self.lista_historia.yview)

        # Przycisk czyszczenia historii
        tk.Button(
            rodzic,
            text="WYCZYŚĆ HISTORIĘ",
            font=("Courier New", 8),
            bg=KOL_AKCENT,
            fg=KOL_TEKST_DIM,
            relief="flat",
            cursor="hand2",
            command=self._wyczysc_historie
        ).pack(fill="x", pady=(8, 0), ipady=4)

    # ─── LOGIKA ──────────────────────────────────────────────────────────────
    def _wybierz_plik(self):
        sciezka = filedialog.askopenfilename(
            title="Wybierz plik do wysłania",
            filetypes=[("Wszystkie pliki", "*.*")]
        )
        if not sciezka:
            return

        self.sciezka_pliku = sciezka
        self.sha256 = None

        nazwa = os.path.basename(sciezka)
        rozmiar = os.path.getsize(sciezka)
        rozmiar_txt = self._formatuj_rozmiar(rozmiar)

        self.wybrany_plik.set(nazwa)
        self.lbl_info_plik.config(
            text=f"Rozmiar: {rozmiar_txt} | Ścieżka: {sciezka}",
            fg=KOL_TEKST
        )
        self.lbl_sha.config(text="SHA256: obliczanie...", fg=KOL_TEKST_DIM)
        self.status_txt.set("Obliczam sumę SHA256...")
        self._set_btn_wyslij_enabled(False)

        # Oblicz SHA256 w tle
        def oblicz():
            try:
                sha = oblicz_sha256(sciezka)
                self.sha256 = sha

                def ui_ok():
                    self.lbl_sha.config(text=f"SHA256:\n{sha}", fg=KOL_TEKST_DIM)
                    self.status_txt.set("Gotowy do wysyłki")
                    # Nie uzależniaj od SSH/TCP22 – UFTP może działać mimo tego.
                    self._set_btn_wyslij_enabled(True)

                self._ui(ui_ok)

            except Exception as e:
                traceback.print_exc()

                def ui_err():
                    self.lbl_sha.config(text=f"SHA256: BŁĄD ({e})", fg=KOL_PODSWIETL)
                    self.status_txt.set("Błąd obliczania SHA256")
                    self._set_btn_wyslij_enabled(False)
                    messagebox.showerror("Błąd SHA256", f"Nie udało się obliczyć SHA256:\n{e}")

                self._ui(ui_err)

        threading.Thread(target=oblicz, daemon=True).start()

    def _wyslij(self):
        if self.wysylanie:
            return

        if not self.sciezka_pliku:
            messagebox.showwarning("Brak pliku", "Wybierz plik do wysłania.")
            return

        if not self.sha256:
            messagebox.showwarning("Brak SHA256", "Poczekaj na zakończenie obliczania SHA256.")
            return

        # Nie blokujemy wysyłki na podstawie braku SSH/22.
        if not self.polaczenie_ok:
            self.status_txt.set("Uwaga: host diody nie odpowiada na ping/SSH. Próbuję wysyłkę UFTP...")

        self.wysylanie = True
        self.btn_wyslij.config(state="disabled", text=" WYSYŁANIE...")
        self.pasek_postepu["value"] = 0
        self.lbl_procent.config(text="0%", fg=KOL_SUKCES)
        self.lbl_postep_txt.config(text="Przygotowanie wysyłki...", fg=KOL_TEKST_DIM)
        self.status_txt.set("Wysyłanie pliku...")

        threading.Thread(target=self._wykonaj_wysylke, daemon=True).start()

    def _wykonaj_wysylke(self):
        sciezka = self.sciezka_pliku
        nazwa = os.path.basename(sciezka)
        czas_start = time.time()
        plik_sha = sciezka + ".sha256"

        try:
            # Zapisz plik SHA256 (LF, kompatybilny z Linux)
            with open(plik_sha, "w", newline="\n", encoding="ascii") as f:
                f.write(f"{self.sha256} *{nazwa}\n")

            self._animuj_postep(0, 15, 0.02)
            self._ui(self.lbl_postep_txt.config, text="Inicjalizacja transferu UFTP...", fg=KOL_TEKST_DIM)

            # Zbuduj komendę uftp.exe
            cmd = [
                UFTP_EXE,
                "-o",
                "-I", INTERFEJS,
                "-R", PREDKOSC,
                "-x", POWTORZENIA,
            ]

            # Hash (jeśli wersja wspiera)
            # Zostawiamy -h sha256; jeśli Twoja wersja kiedyś będzie marudzić, usuń te 2 elementy.
            cmd += ["-h", UFTP_HASH]

            # Szyfrowanie wyłączone domyślnie (wcześniej "Invalid keytype")
            if UFTP_UZYJ_SZYFROWANIA:
                # UWAGA: ta składnia może być inna zależnie od wersji uftp.exe
                # cmd += ["-Y", UFTP_CIPHER]
                pass

            cmd += [sciezka, plik_sha]

            self._animuj_postep(15, 85, 0.01)
            self._ui(self.lbl_postep_txt.config, text=f"Wysyłanie: {nazwa}", fg=KOL_TEKST)

            wynik = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )

            czas_koniec = time.time()
            czas_trwania = round(czas_koniec - czas_start, 1)

            if wynik.returncode == 0:
                self._animuj_postep(85, 100, 0.01)

                self._ui(self.lbl_postep_txt.config, text=f"✓ Wysłano pomyślnie w {czas_trwania}s", fg=KOL_SUKCES)
                self._ui(self.lbl_procent.config, text="100%", fg=KOL_SUKCES)
                self._ui(self.status_txt.set, f"Ostatnia wysyłka: {nazwa} – sukces")
                self._ui(self._dodaj_do_historii, nazwa, "OK", czas_trwania)

                komunikat = (
                    f"Plik wysłany pomyślnie!\n\n"
                    f"Plik: {nazwa}\n"
                    f"Czas: {czas_trwania}s\n"
                    f"SHA256: {self.sha256[:32]}..."
                )
                self._ui(messagebox.showinfo, "Sukces", komunikat)

            else:
                stderr_txt = (wynik.stderr or "").strip()
                stdout_txt = (wynik.stdout or "").strip()
                szczegoly = stderr_txt if stderr_txt else stdout_txt if stdout_txt else "Brak komunikatu błędu"

                self._ui(self.lbl_postep_txt.config, text="✗ Błąd wysyłki", fg=KOL_PODSWIETL)
                self._ui(self.lbl_procent.config, text="BŁĄD", fg=KOL_PODSWIETL)
                self._ui(self.status_txt.set, f"Błąd wysyłki: {nazwa}")
                self._ui(self._dodaj_do_historii, nazwa, "BŁĄD", czas_trwania)

                self._ui(
                    messagebox.showerror,
                    "Błąd transferu",
                    f"Wysyłanie nie powiodło się!\n\n{szczegoly}"
                )

        except subprocess.TimeoutExpired:
            self._ui(self.lbl_postep_txt.config, text="✗ Przekroczono czas oczekiwania", fg=KOL_PODSWIETL)
            self._ui(self.status_txt.set, "Timeout podczas wysyłki")
            self._ui(messagebox.showerror, "Timeout", "Wysyłanie przekroczyło limit czasu (5 min).")

        except FileNotFoundError:
            self._ui(
                messagebox.showerror,
                "Błąd",
                f"Nie znaleziono uftp.exe!\nSprawdź ścieżkę: {UFTP_EXE}"
            )

        except Exception as e:
            traceback.print_exc()
            self._ui(messagebox.showerror, "Nieoczekiwany błąd", str(e))

        finally:
            # Usuń tymczasowy plik SHA256
            try:
                if os.path.exists(plik_sha):
                    os.remove(plik_sha)
            except Exception:
                pass

            def ui_final():
                self.wysylanie = False
                self.btn_wyslij.config(state="normal", text="▶ WYŚLIJ PRZEZ DIODĘ")

            self._ui(ui_final)

    def _animuj_postep(self, od: int, do: int, opoznienie: float):
        """
        Animacja wykonywana z wątku roboczego.
        Aktualizacja GUI opakowana przez self._ui.
        """
        for i in range(od, do + 1):
            self._ui(self.pasek_postepu.config, value=i)
            self._ui(self.lbl_procent.config, text=f"{i}%")
            time.sleep(opoznienie)

    def _dodaj_do_historii(self, nazwa: str, status: str, czas_s: float):
        znacznik = datetime.now().strftime("%H:%M:%S")
        ikona = "✓" if status == "OK" else "✗"
        wpis = f"{ikona} [{znacznik}] {nazwa} ({czas_s}s)"
        self.lista_historia.insert(0, wpis)

        # Kolor wpisu
        if status == "OK":
            self.lista_historia.itemconfig(0, fg=KOL_SUKCES)
        else:
            self.lista_historia.itemconfig(0, fg=KOL_PODSWIETL)

    def _wyczysc_historie(self):
        self.lista_historia.delete(0, tk.END)

    def _sprawdzaj_polaczenie(self):
        """Sprawdza osiągalność hosta diody co 5 sekund (ping/SSH fallback)."""

        def petla():
            while True:
                ok = sprawdz_polaczenie()
                self.polaczenie_ok = ok

                def ui_update():
                    if ok:
                        self.lbl_polaczenie.config(
                            text=f"● HOST OK {IP_DIODY}",
                            fg=KOL_SUKCES
                        )
                    else:
                        # Nie traktujemy tego jako twardy blocker dla UFTP
                        self.lbl_polaczenie.config(
                            text="● BRAK SSH/PING (UFTP może działać)",
                            fg=KOL_OSTRZEZENIE
                        )

                    # Przycisk aktywny jeśli mamy plik + sha i nie trwa wysyłka
                    if self.sciezka_pliku and self.sha256 and not self.wysylanie:
                        self._set_btn_wyslij_enabled(True)
                    elif not self.sciezka_pliku or not self.sha256:
                        self._set_btn_wyslij_enabled(False)

                self._ui(ui_update)
                time.sleep(5)

        threading.Thread(target=petla, daemon=True).start()

    @staticmethod
    def _formatuj_rozmiar(bajty: int) -> str:
        for jednostka in ["B", "KB", "MB", "GB"]:
            if bajty < 1024:
                return f"{bajty:.1f} {jednostka}"
            bajty /= 1024
        return f"{bajty:.1f} TB"


if __name__ == "__main__":
    app = NadawcaApp()
    app.mainloop()