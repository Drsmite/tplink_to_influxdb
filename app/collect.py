#!/usr/bin/env python3
#
# Poll TP-Link smart-plugs for energy usage readings and send into InfluxDB
#
# pip install pyyaml influxdb-client PyP100 python-kasa
#
# Copyright (c) 2022 B Tasker
#
# Released under BSD-3-Clause License, see LICENSE in the root of the project repo
#

import asyncio
import os
import sys
import time
import yaml
import inspect

from influxdb import InfluxDBClient
from kasa import SmartPlug
from PyP100 import PyP110

dirname = os.path.dirname(inspect.getfile(inspect.currentframe()))
filename = os.path.join(dirname, '../example/config.yml')

def load_config():
    ''' Read the config file
    
    '''
    with open(filename) as file:
        try:
            config = yaml.safe_load(file)
        except yaml.YAMLError as e:
            print(e)
            config = False
            
    return config
    

def main():
    ''' Main Entry point
    
    Read the config, initialise readers etc
    '''

    config = load_config()
    if not config:
        sys.exit(1)
    
    # Create the InfluxDB clients
    influxes = []

    for influx in config["influxdb"]:
            c = InfluxDBClient(influx["host"],influx["port"],influx["user"],influx["password"],influx["database"])
            influxes.append({"name": influx['name'],
                             "conn": c
                             })

    stats = {}
    start_time = time.time_ns()

    for kasa in config["kasa"]["devices"]:
        try:
            now_usage_w, today_usage = poll_kasa(kasa['ip'])
        except:
            print(f"Failed to communicate with device {kasa['name']}")
            continue
        if now_usage_w is False:
            print(f"Failed to communicate with device {kasa['name']}.  Adding empty entry.")
            now_usage_w = 0
        
        if today_usage == 0:
            today_usage = 1
        
        print(f"Plug: {kasa['name']} using {now_usage_w}W, today: {today_usage} Wh")
        stats[kasa['name']] = {
                "today_usage" : today_usage,
                "now_usage_w" : now_usage_w,
                "time" : start_time
            }

    #for tapo in config["tapo"]["devices"]:
    #    now_usage_w, today_usage = poll_tapo(tapo['ip'], config["tapo"]["user"], config["tapo"]["passw"])
    #    if now_usage_w is False:
    #        print(f"Failed to communicate with device {tapo['name']}")
    #        continue
    #    
    #    print(f"Plug: {tapo['name']} using {now_usage_w}W, today: {today_usage/1000} kWh")
    #    stats[tapo['name']] = {
    #            "today_usage" : today_usage,
    #            "now_usage_w" : now_usage_w,
    #            "time" : start_time
    #        }
        
    # Build a buffer of points
    points_buffer = buildPointsBuffer(stats)
    
    if len(points_buffer) > 0:
        # Iterate through the InfluxDB connections and send the data over
        for dest in influxes:
            res = sendToInflux(dest['conn'],
                        points_buffer
                        )
            if not res:
                print(f"Failed to send points to {dest['name']}")
            else:
                print(f"Wrote {len(points_buffer)} points to {dest['name']}")

        
def poll_kasa(ip):
    ''' Poll a TP-Link Kasa smartplug
    
    TODO: need to add some exception handling to this
    '''
    
    # Connect to the plug and receive stats
    p = SmartPlug(ip)
    asyncio.run(p.update())
        
    # emeter_today relies on external connectivity - it uses NTP to keep track of time
    # you need to allow UDP 123 outbound if you're restricting the plug's external connectivity
    # otherwise you'll get 0 or 0.001 back instead of the real value
    # 
    # See https://github.com/home-assistant/core/issues/45436#issuecomment-766454897
    #
    
    # Convert from kWh to Wh
    try:
        today_usage = p.emeter_today * 1000
        usage_dict = p.emeter_realtime
        now_usage_w = usage_dict["power_mw"] / 1000
    except:
        today_usage = 0
        now_usage_w = 0

    return now_usage_w, today_usage


def poll_tapo(ip, user, passw):
    ''' Poll a TP-Link Tapo smartplug
    '''
    
    try:
        p110 = PyP110.P110(ip, user, passw)
        p110.handshake() #Creates the cookies required for further methods
        p110.login() #Sends credentials to the plug and creates AES Key and IV for further methods        
        usage_dict = p110.getEnergyUsage()
    except:
        return False, False

    today_usage = usage_dict["result"]["today_energy"]
    now_usage_w = usage_dict["result"]["current_power"] / 1000
    
    return now_usage_w, today_usage
    

def buildPointsBuffer(points):
    ''' Iterate through the collected stats and write them out to InfluxDB
    '''
    
    # Initialize

    points_buffer = []
    
    for point in points:
             
        # Build a point 
        dataPoint = {
            "measurement": "Iotawatt",
            #"tags": {
            #    "host": point,
            #},
            "time": points[point]['time'],
            "fields": {
                point: float(points[point]['now_usage_w'])
            }
        }
        #p = influxdb_client.Point("power_watts").tag("host", point).field("consumption", float(points[point]['now_usage_w'])).time(points[point]['time'])
        points_buffer.append(dataPoint)
        
        
        # If we've captured usage, add a point for that
        if points[point]['today_usage']:
            dataPoint = {
            "measurement": "Iotawatt",
            #"tags": {
            #    "host": point,
            #},
            "time": points[point]['time'],
            "fields": {
                point+"_Wh": int(float(points[point]['today_usage']))
            }
            }
            #p = influxdb_client.Point("power_watts").tag("host", point).field("watts_today", int(float(points[point]['today_usage']))).time(points[point]['time'])
            points_buffer.append(dataPoint)
        
    return points_buffer


def sendToInflux(influxdb_client, points_buffer):
    ''' Take a set of values, and send them on to InfluxDB
    '''
    try:
        influxdb_client.write_points(points_buffer)
        return True
    except:
        return False


if __name__ == "__main__":
    main()
