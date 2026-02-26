# Instrukcja Wdrożenia – Wirtualna Dioda Danych

Wersja 1.0 · 2026

VirtualBox · Oracle Linux 8 · UFTP · Python GUI

Środowisko testowe imitujące jednostronny transfer danych: Windows A
(nadawca) → Dioda (Oracle Linux 8) → Windows B (odbiorca)

## 1. ARCHITEKTURA SYSTEMU

Adresy IP:

Windows A – 192.168.10.1 – nadawca

Oracle Linux 8 (eth0) – 192.168.10.254 – dioda – odbiór

Oracle Linux 8 (eth1) – 192.168.20.254 – dioda – wysyłka

Windows B – 192.168.20.1 – odbiorca

## 2. KONFIGURACJA VIRTUALBOX – TWORZENIE VM

2.1 Tworzenie VM – Oracle Linux 8 (Dioda):

• Typ: Linux

• Wersja: Oracle (64‑bit)

• RAM: 4096 MB

• Dysk: 30 GB

Karta 1 – Sieć wewnętrzna: siec-nadawcy

Karta 2 – Sieć wewnętrzna: siec-odbiorcy

2.2 Tworzenie VM – Windows A:

RAM: 4096 MB, dysk: 50 GB

Karta 1: siec‑nadawcy

2.3 Tworzenie VM – Windows B:

RAM: 4096 MB, dysk: 50 GB

Karta 1: siec‑odbiorcy

## 3. PRZYGOTOWANIE PAKIETÓW OFFLINE

Oracle Linux 8 nie ma dostępu do internetu – pakiety muszą zostać
pobrane na maszynie z internetem.

Polecenia:
```bash
sudo dnf install epel-release -y

mkdir ~/pakiety-dioda

cd ~/pakiety-dioda
```

Pobieranie pakietów:
```bash
sudo dnf download --resolve --destdir ~/pakiety-dioda inotify-tools
clamav clamav-update clamav-lib iptables-services

# Pobieranie bazy ClamAV:

wget https://database.clamav.net/main.cvd

wget https://database.clamav.net/daily.cvd

wget https://database.clamav.net/bytecode.cvd
```
## 4. KONFIGURACJA ORACLE LINUX 8

# Włączenie SELinux:
```bash
sudo nano /etc/selinux/config

SELINUX=enforcing

sudo reboot
```
Konfiguracja adresów sieciowych:
```bash
eth0 – 192.168.10.254/24

eth1 – 192.168.20.254/24

# Wyłączenie firewalld, włączenie iptables:

sudo systemctl stop firewalld

sudo systemctl disable firewalld

sudo systemctl enable iptables

sudo systemctl start iptables

# Wyłączenie routingu w kernel:

sudo nano /etc/sysctl.conf

net.ipv4.ip_forward = 0

net.ipv4.conf.all.forwarding = 0

sysctl –p

# Utworzenie użytkownika diode:

useradd -r -s /sbin/nologin -d /opt/dioda dioda

chown -R dioda:dioda /opt/diode

# Zablokowanie dostępu root:

nano /etc/ssh/sshd_config

PermitRootLogin no

PasswordAuthentication no

systemctl restart sshd

# Ustawienie sudo na jednego admina:

useradd admin_dioda

passwd admin_dioda

usermod -aG wheel admin_dioda

# Ustawienie immutable na pliki konfiguracyjne:

chattr +i /opt/dioda/bin/dioda.sh

chattr +i /etc/systemd/system/dioda.service

chattr +i /etc/sysconfig/iptables
```
## 5. SKRYPT DIODY Z KOLEJKOWANIEM

Skrypt zapewnia:

• Weryfikację SHA256

• Skan antywirusowy ClamAV

• Kolejkowanie do 5 plików

• Limit zapełnienia dysku – 80%

• Transfer jednostronny

Utworzenie skryptu:
```bash
sudo nano /usr/local/bin/dioda.sh
```
(wklej zawartość pliku dioda.sh)

Rejestracja jako usługa:
```bash
sudo nano /etc/systemd/system/dioda.service

sudo systemctl enable dioda

sudo systemctl start dioda
```
## 6. KONFIGURACJA WINDOWS

Konfiguracja IP:

Windows A – 192.168.10.1 / 255.255.255.0 / brama 192.168.10.254

Windows B – 192.168.20.1 / 255.255.255.0 / brama 192.168.20.254

Instalacja UFTP:

C:\uftp\\

\- uftp.exe

\- uftpd.exe

\- uftp_keymgt.exe

Odblokowanie portu na WINDOWS UDP 1044.

## 7. SKRYPTY PYTHON – NADAWCA I ODBIORCA

Oba skrypty używają tylko bibliotek wbudowanych (tkinter, subprocess,
threading, hashlib).

Nadawca:

• wybór pliku

• obliczanie SHA256

• pasek postępu

• historia wysyłki

Odbiorca:

• automatyczny nasłuch

• wykrywanie plików

• powiadomienia

• lista odebranych plików

## 8. LISTA PLIKÓW I ROZMIESZCZENIE

Windows A:

nadawca_gui.py → C:\uftp\\

uftp.exe → C:\uftp\\

Windows B:

odbiorca_gui.py → C:\uftp\\

uftpd.exe → C:\uftp\\

Oracle Linux 8:

dioda.sh → /usr/local/bin/

dioda.service → /etc/systemd/system/


## 9. LIMITY I PARAMETRY SYSTEMU

MAX_ROZMIAR_MB – 1024 MB

MAX_DYSK – 80%

MAKS_JEDNOCZESNYCH – 5

Prędkość – 50 Mbps

Powtórzenia – 3

Przykładowe czasy transferu:

100 MB – 20 s

500 MB – 1.5 min

1 GB – 3 min

10 GB – 30 min

