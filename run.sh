#!/bin/bash

SCRIPT_NAME="solis2mqtt.py --service"
HEALTH_PROBE="/tmp/ECO_HEALTH"

while true; do

    echo "Starting ${SCRIPT_NAME}"
    rm -f ${HEALTH_PROBE}

	start_of_script=$(date +%s%3N)

    python ${SCRIPT_NAME}
    error_level=$?

	end_of_script=$(date +%s%3N)
	script_duration=$((end_of_script - start_of_script))

    # echo "Errorlevel: ${error_level}"

    if [ ${error_level} -eq 1 ]; then
        # script execution error
        sleep_interval=20
    elif [ ${error_level} -eq 2 ]; then
        # inverter unreachable and sun is down
        sleep_interval=300
    elif [ ${error_level} -eq 3 ]; then
        # inverter unreachable and sun is up, so try again soon
        sleep_interval=10
    else
        # default, sun is (almost) up or inverter is reachable
        sleep_interval=60
    fi
    echo "sleep_interval: ${sleep_interval} seconds"

    remaining_time=$((sleep_interval*1000 - script_duration))
	sleep_time=$((remaining_time > 0 ? remaining_time : 0))

    echo "Run took $((script_duration/1000)) seconds"
    # echo "$(date -u --iso-8601='seconds') Now waiting for $((sleep_time/1000)) seconds until $(date -d "+$((sleep_time/1000)) seconds")"
    echo "Now waiting for $((sleep_time/1000)) seconds until $(date -d "+$((sleep_time/1000)) seconds")"
    touch ${HEALTH_PROBE}
    sleep $(printf %f "$((sleep_time))e-3")
    echo "Done waiting"

    # sleep ${sleep_interval}
done