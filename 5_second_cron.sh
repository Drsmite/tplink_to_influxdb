#!/bin/bash
while true
do
 /usr/bin/python3 /home/eric/tplink_to_influxdb/app/collect.py
 /usr/bin/sleep 5
done
