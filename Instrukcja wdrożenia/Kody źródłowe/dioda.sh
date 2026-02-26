#!/bin/bash
# Wirtualna Dioda z kolejkowaniem – Oracle Linux 8
# Windows A (192.168.10.0/24) -> Oracle Linux (dioda) -> Windows B (192.168.20.0/24)

set -u
umask 027

# ──────────────────────────────────────────────────────────────────────────────
# KONFIGURACJA
# ──────────────────────────────────────────────────────────────────────────────

# Nazwy interfejsów (iptables: MUSZĄ być nazwy interfejsów)
IF_NADAWCA="enp0s3"      # strona 192.168.10.0/24
IF_ODBIORCA="enp0s8"     # strona 192.168.20.0/24

# Lokalne adresy IP diody (uftp/uftpd: używamy IP)
IP_NADAWCA_LOCAL="192.168.10.254"
IP_ODBIORCA_LOCAL="192.168.20.254"

PODSIEC_NADAWCY="192.168.10.0/24"
PODSIEC_ODBIORCY="192.168.20.0/24"

BUFOR="/opt/dioda/bufor"
LOG_DIR="/opt/dioda/logi"
LOG="$LOG_DIR/dioda.log"

MAX_ROZMIAR_MB=1024
MAX_DYSK=80
MAKS_JEDNOCZESNYCH=5
WYMAGAJ_SHA=1

UFTP_BIN="/usr/bin/uftp"
UFTPD_BIN="/usr/bin/uftpd"
CLAMSCAN_BIN="/usr/bin/clamscan"
INOTIFYWAIT_BIN="/usr/bin/inotifywait"

# Parametry wysyłki Linux -> Windows B
UFTP_RATE="50000"
UFTP_RETRY="3"

# ──────────────────────────────────────────────────────────────────────────────
# PRZYGOTOWANIE
# ──────────────────────────────────────────────────────────────────────────────
mkdir -p "$BUFOR" "$LOG_DIR"
touch "$LOG"
chmod 640 "$LOG" 2>/dev/null || true

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"
}

sprawdz_miejsce() {
    df /opt/dioda --output=pcent 2>/dev/null | tail -1 | tr -d ' %'
}

rozmiar_mb() {
    local plik="$1"
    echo $(( $(stat -c%s "$plik" 2>/dev/null || echo 0) / 1024 / 1024 ))
}

liczba_aktywnych() {
    find "$BUFOR" -maxdepth 1 -type f ! -name "*.sha256" ! -name "*.tmp" | wc -l
}

normalizuj_sha_crlf() {
    local sha_file="$1"
    sed -i 's/\r$//' "$sha_file"
}

wymagane_binaria_ok() {
    local brak=0
    for b in "$UFTP_BIN" "$UFTPD_BIN" "$INOTIFYWAIT_BIN"; do
        if [ ! -x "$b" ]; then
            log "BLAD: Brak wymaganego pliku wykonywalnego: $b"
            brak=1
        fi
    done
    return $brak
}

log "Dioda uruchomiona z kolejkowaniem"

if ! wymagane_binaria_ok; then
    log "BLAD: Brak wymaganych narzedzi - koniec"
    exit 1
fi

# ──────────────────────────────────────────────────────────────────────────────
# IPTABLES
# ──────────────────────────────────────────────────────────────────────────────
iptables -F
iptables -P INPUT DROP
iptables -P OUTPUT DROP
iptables -P FORWARD DROP

# Loopback
iptables -A INPUT  -i lo -j ACCEPT
iptables -A OUTPUT -o lo -j ACCEPT

# Ruch powiązany
iptables -A INPUT  -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# STRONA NADAWCY (Windows A -> dioda)
iptables -A INPUT  -i "$IF_NADAWCA" -s "$PODSIEC_NADAWCY" -j ACCEPT
iptables -A OUTPUT -o "$IF_NADAWCA" -d "$PODSIEC_NADAWCY" -j ACCEPT

# Multicast po stronie nadawcy (UFTP announce)
iptables -A INPUT  -i "$IF_NADAWCA" -d 224.0.0.0/4 -j ACCEPT
iptables -A OUTPUT -o "$IF_NADAWCA" -d 224.0.0.0/4 -j ACCEPT

# SSH admin (opcjonalnie)
iptables -A INPUT  -i "$IF_NADAWCA" -p tcp --dport 22 -s "$PODSIEC_NADAWCY" -j ACCEPT
iptables -A OUTPUT -o "$IF_NADAWCA" -p tcp --sport 22 -d "$PODSIEC_NADAWCY" -j ACCEPT

# STRONA ODBIORCY (dioda -> Windows B)
iptables -A OUTPUT -o "$IF_ODBIORCA" -d "$PODSIEC_ODBIORCY" -j ACCEPT
iptables -A OUTPUT -o "$IF_ODBIORCA" -d 224.0.0.0/4 -j ACCEPT

# TESTOWO: pozwól na odpowiedzi z sieci odbiorcy (UFTP handshake/ACK)
iptables -A INPUT  -i "$IF_ODBIORCA" -s "$PODSIEC_ODBIORCY" -j ACCEPT

log "Reguly iptables zastosowane"

# ──────────────────────────────────────────────────────────────────────────────
# FUNKCJA PRZETWARZANIA PLIKU
# ──────────────────────────────────────────────────────────────────────────────
przetworz_plik() {
    local plik="$1"
    local pelna_sciezka="$BUFOR/$plik"
    local plik_sha="$BUFOR/$plik.sha256"
    local rozmiar wait_i

    if [ ! -f "$pelna_sciezka" ]; then
        log "Pominieto (plik nie istnieje): $plik"
        return 1
    fi

    rozmiar=$(rozmiar_mb "$pelna_sciezka")
    if [ "$rozmiar" -gt "$MAX_ROZMIAR_MB" ]; then
        log "ODRZUCONO - za duzy: ${rozmiar}MB: $plik"
        rm -f "$pelna_sciezka" "$plik_sha"
        return 1
    fi

    if [ "$WYMAGAJ_SHA" -eq 1 ]; then
        for wait_i in {1..20}; do
            [ -f "$plik_sha" ] && break
            sleep 0.5
        done

        if [ ! -f "$plik_sha" ]; then
            log "BRAK SHA256 - odrzucono: $plik"
            rm -f "$pelna_sciezka"
            return 1
        fi
    fi

    if [ -f "$plik_sha" ]; then
        normalizuj_sha_crlf "$plik_sha"

        cd "$BUFOR" || {
            log "BLAD: Nie mozna przejsc do BUFOR: $BUFOR"
            return 1
        }

        if ! sha256sum -c "$plik.sha256" >> "$LOG" 2>&1; then
            log "BLAD SHA256 - odrzucono: $plik"
            rm -f "$pelna_sciezka" "$plik_sha"
            return 1
        fi

        log "SHA256 OK: $plik"
    fi

    if [ -x "$CLAMSCAN_BIN" ]; then
        "$CLAMSCAN_BIN" "$pelna_sciezka" >> "$LOG" 2>&1
        case $? in
            0) log "Skan AV OK: $plik" ;;
            1)
                log "ZAGROZENIE AV - odrzucono: $plik"
                rm -f "$pelna_sciezka" "$plik_sha"
                return 1
                ;;
            *)
                log "BLAD skanera AV - odrzucono (bezpiecznie): $plik"
                rm -f "$pelna_sciezka" "$plik_sha"
                return 1
                ;;
        esac
    else
        log "UWAGA: clamscan nie znaleziony, pomijam skan AV: $plik"
    fi

    # Linux -> Windows B (bez -Y/-h na start; SHA weryfikujemy wcześniej)
    "$UFTP_BIN" -o \
        -I "$IP_ODBIORCA_LOCAL" \
        -R "$UFTP_RATE" \
        -x "$UFTP_RETRY" \
        "$pelna_sciezka" >> "$LOG" 2>&1

    if [ $? -eq 0 ]; then
        log "Przekazano OK: $plik"
        rm -f "$pelna_sciezka" "$plik_sha"
    else
        log "BLAD przekazania: $plik"
        return 1
    fi

    return 0
}

# ──────────────────────────────────────────────────────────────────────────────
# URUCHOM ODBIORNIK UFTPD (Windows A -> dioda Linux)
# ──────────────────────────────────────────────────────────────────────────────
pkill -x uftpd 2>/dev/null || true
sleep 1

# UWAGA: bez -n / -q
"$UFTPD_BIN" -D "$BUFOR" -I "$IP_NADAWCA_LOCAL" >> "$LOG" 2>&1 &
sleep 2

if pgrep -x uftpd >/dev/null 2>&1 || ss -ulnp | grep -q ':1044'; then
    log "Nasluchuje na $IP_NADAWCA_LOCAL:1044"
else
    log "BLAD: uftpd nie uruchomil sie poprawnie"
fi

# ──────────────────────────────────────────────────────────────────────────────
# PETLA GLOWNA Z KOLEJKOWANIEM
# ──────────────────────────────────────────────────────────────────────────────
"$INOTIFYWAIT_BIN" -m -e close_write --format '%w|%e|%f' "$BUFOR" | \
while IFS='|' read -r path action plik; do
    [[ -z "$plik" ]] && continue
    [[ "$plik" == *.sha256 ]] && continue
    [[ "$plik" == *.tmp ]] && continue

    sleep 2

    wypelnienie=$(sprawdz_miejsce)
    if [ -z "$wypelnienie" ]; then
        log "BLAD: Nie mozna odczytac wypelnienia dysku"
        continue
    fi

    if [ "$wypelnienie" -gt "$MAX_DYSK" ]; then
        log "Dysk ${wypelnienie}% - czekam..."
        while [ "$(sprawdz_miejsce)" -gt "$MAX_DYSK" ]; do
            sleep 5
        done
        log "Miejsce zwolnione - wznawiam"
    fi

    aktywne=$(liczba_aktywnych)
    if [ "$aktywne" -gt "$MAKS_JEDNOCZESNYCH" ]; then
        log "Kolejka pelna ($aktywne) - czekam..."
        while [ "$(liczba_aktywnych)" -gt "$MAKS_JEDNOCZESNYCH" ]; do
            sleep 3
        done
        log "Kolejka zwolniona"
    fi

    log "Odebrano: $plik (dysk: ${wypelnienie}%)"
    przetworz_plik "$plik" &
done