#!/bin/bash

sudo bash -c '
echo "Copy newer files when present"
cp -v -u *.py run.sh defaults_config.yaml config.yaml solis_modbus.yaml /opt/solis2mqtt
chown -R solis2mqtt:solis2mqtt /opt/solis2mqtt

if [ provisioning/etc/systemd/system/solis2mqtt.servic -nt /etc/systemd/system/solis2mqtt.service ]
then
    cp -v -u provisioning/etc/systemd/system/solis2mqtt.service /etc/systemd/system
    systemctl daemon-reload
    echo "Renew service"
fi

echo "Stop/start service"
systemctl stop solis2mqtt.service
systemctl start solis2mqtt.service
'

# journalctl -u solis2mqtt.service -f --output=short-iso-precise