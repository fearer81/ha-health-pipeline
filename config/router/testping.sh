#!/bin/sh

# keep wifi alive
check_network() {
    if /bin/ping -q -c 1 8.8.8.8 &> /dev/null; then
        return 0 # Network is available
    else
        return 1 # Network is not available
    fi
}

# Main script logic
    if check_network; then
        # echo "$(date) ===-> OK! " >>/root/inetmonit.log
	logger -p notice -t testpinglog "OK"
	# echo "$(date) ===-> OK! "
    else
        echo "$(date) ===-> NOK! Rebooting!" >>/root/inetmonit.log
	logger -p err -t testpinglog "NOK! Rebooting!"
        # /sbin/wifi down && /sbin/wifi up
	/sbin/reboot
    fi