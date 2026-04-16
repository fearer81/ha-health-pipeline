ssh() {
    case "$1" in
        ap)     dbclient -p 3022 192.168.1.9 ;;
        ha)     dbclient -m hmac-sha2-256 192.168.1.41 ;;
        debian) dbclient 192.168.1.49 ;;
        dell)   dbclient 192.168.1.40 ;;
        *)      /usr/bin/ssh "$@" ;;
    esac
}
