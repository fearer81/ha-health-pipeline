# Funkcja skoku przez Debiana
ssh() {
    case "$1" in
        ap)     dbclient -p 3022 192.168.1.9 ;;
        # Łączymy się z Debianem i zmuszamy go do odpalenia SSH do HA
        ha)     echo "Skok do HA przez Debiana (1.49)..."
                dbclient -t 192.168.1.49 "ssh root@192.168.1.41" ;;
        debian) dbclient 192.168.1.49 ;;
        dell)   dbclient 192.168.1.40 ;;
        win)    dbclient -i /root/.ssh/id_dropbear fear8@192.168.1.2 ;;
        *)      /usr/bin/ssh "$@" ;;
    esac
}
