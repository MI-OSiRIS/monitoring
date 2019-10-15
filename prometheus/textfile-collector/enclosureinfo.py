#!/usr/bin/env python3

# this script fetches information about Dell MD3060e enclosures using the 'secli' or 'shmcli' tools
# presumably it would apply to any type of enclosure addressable by these tools 
# output into Prometheus metrics designed for use with the text collector
# the script directly outputs a list of metrics which you can pipe into a file in desired location
# It should be created atomically by piping into tmp file and moving tmp file into final location

# The user running the script must have sudo privileges to run the utility, or be root

# status metric states:  0 is good, 1 is warn, 2 is crit
# for the enclosure_drive_slot_status a missing drive is a warn, a bad slot status is critical
# (tools report slot status OK even if a drive is totally dead or dying)

import subprocess
import os
import json
import sys

# Default installation is /opt/dell/StorageEnclosureManagement/StorageEnclosureCLI/bin/secli
cli = '/opt/dell/StorageEnclosureManagement/StorageEnclosureCLI/bin/secli'

if not os.path.isfile(cli):
    sys.exit(1)

# secli expects to find utilities in path (lspci, etc) which may be in sbin
nenv = os.environ
nenv['PATH']= nenv['PATH'] + ':/sbin:/usr/sbin'

# three element tuple 
# 0:  command to run
# 1:  top level subkey 
# 2:  subkey containing component list 

mapcmd = { 
    'enc': ('list physical enclosures', 'Enclosures', 'Enclosure'),
    'temp': ('list temp sensors', 'TemperatureSensors', 'TemperatureSensor'),
    'fan': ('list fans', 'Fans', 'Fan'),
    'ps': ('list power supplies', 'PowerSupplies', 'PowerSupply'),
    'driveslot': ('list drive slots', 'DriveSlots', 'DriveSlot'),  # also includes info on drive in slot
    'voltage': ('list voltage sensors', 'VoltageSensors', 'VoltageSensor'),
    'current': ('list current sensors', 'CurrentSensors', 'CurrentSensor')
}


# 'WARN' is a guess
# when fetching this default to 2 if not found
mapstatus = {
    'OK': 0,
    'WARN': 1,
    'CRITICAL': 2,
    'UNKNOWN': 2  
}

# boolean fields are 'is failed' so a TRUE status is bad.  
mapbool = {
    'TRUE': 2,
    'FALSE': 0
}

# fetch data using command from cli var and return an array of dictionaries as decoded from the JSON results
def fetch_data(type,enc=None):
    cmd = [cli, mapcmd[type][0], '-outputformat=json']
    if type != 'enc':
        cmd = cmd + [ '-enc={0}'.format(enc) ]

    try:
        json_data = subprocess.check_output(cmd,env=nenv, stderr=subprocess.DEVNULL)
        decoded = json.loads(json_data)
        # print(decoded)
        # many component listings are repeated
        # Ex:  decoded['Responses']['Response']['Fans'][0-1]['Fan'][0...x fans] 
        # Fans[0] and Fans[1] are clearly the same set of fans
        # I assume this is because there are 2 redundant EMM to read from and we can just pick up the first index 

        hwdata = decoded['Responses']['Response'][mapcmd[type][1]]

        if hwdata == None:
            return []

        # if there is only 1 emm / 1 set of values does it still return an array? 
        # the json data returned for enclosures does NOT wrap them in an array if there is only one 
        # I'm guessing that it would be an array if there were more than one, and perhaps others might
        # also not be returned as arrays if there is only one component or set of readings (such as in the case of dead EMM?)
        if not isinstance(hwdata,list):
            hwdata = [hwdata]

        components = hwdata[0][mapcmd[type][2]]
         
        if not isinstance(components,list):
            return [components] 
        else:
            return components
    except json.JSONDecodeError as err:
        # continue and try to fetch other outputs
        print("# Bad JSON returned for {}: {}".format(type, err.msg))
    except:
        raise

enclosures = fetch_data('enc')

for enclosure in enclosures:
    enc_status = {}

    if int(enclosure['AlarmCount']) > 0:
        enc_status['ac'] = 2
    
    driveslots = fetch_data('driveslot',enclosure['EnclosureWWID'])
    supplies = fetch_data('ps',enclosure['EnclosureWWID'])
    fans = fetch_data('fan',enclosure['EnclosureWWID'])
    temps = fetch_data('temp',enclosure['EnclosureWWID'])
    volts = fetch_data('voltage', enclosure['EnclosureWWID'])

    # our hardware does not have current sensors so I don't know what fields are in the output

    # drives, fans, supplies, temps all share these labels
    common_labels = 'enclosure_wwn="{}", enclosure_serial="{}", enclosure_name="{}"'.format(
        enclosure['EnclosureWWID'],
        enclosure['ServiceTag'],
        enclosure['ProductName'])
    
    enc_status['slot'] = 0
    enc_status['ps'] = 0
    enc_status['fan'] = 0
    enc_status['volt'] = 0
    enc_status['temp'] = 0

    for slot in driveslots:

        # if a drive is failed there will not be a drive info structure included in the output
        # slot status will still be OK though 
       
        drive = slot.get('Drive', None)
        
        wwn = ""
        serial = ""

        if slot['Status'] != 'OK':
            status = 2
        elif drive == None:
            status = 2
        else:
            wwn_data = next((item for item in drive['DeviceIds']['Descriptor'] if item['@association'] == 'ADDRESSED_LOGICAL_UNIT'), "")
            wwn = wwn_data['#text']
            serial = drive['SerialNumber']
            status = 0

        print('enclosure_drive_info{{serial="{}", wwn="{}",enclosure_slot="{}",drawer="{}",drawer_slot="{}",{}}} 1'
            .format(
                serial, 
                wwn,
                slot['EnclosureSlot'],
                slot['Drawer'],
                slot['DrawerSlot'],
                common_labels
                ))

        print('enclosure_slot_status{{enclosure_slot="{}",drawer="{}",drawer_slot="{}",{}}} {}'
            .format(
                slot['EnclosureSlot'],
                slot['Drawer'],
                slot['DrawerSlot'],
                common_labels,
                status
                ))

        if status > enc_status['slot']: enc_status['slot'] = status
        
    for supply in supplies:
        labels = 'name="{}", {}'.format(supply['Name'],common_labels)
        status = mapstatus.get(supply['Status'], 2)

        print('enclosure_power_status{{{0}}} {1}'.format(labels, status))
        print('enclosure_power_ac_status{{{0}}} {1}'.format(labels, mapbool.get(supply['ACFail'], 2)))
        print('enclosure_power_dc_status{{{0}}} {1}'.format(labels, mapbool.get(supply['DCFail'], 2)))

        if status > enc_status['ps']: enc_status['ps'] = status
   
    for fan in fans:
        status = mapstatus.get(fan['Status'], 2)
        labels = labels = 'name="{}", {}'.format(fan['Name'],common_labels)
        print('enclosure_fan_status{{{0}}} {1}'.format(labels, status))
        print('enclosure_fan_speed_rpm{{{0}}} {1}'.format(labels, fan['RPM']))
        # we could map to a numeric output if we wanted this information
        # codes I have seen (there are surely more):  "3rd Highest Speed", "Intermediate Speed"
        # print('enclosure_fan_speed_step{{{0}}} {1}'.format(labels, fan['SpeedCode']))

        if status > enc_status['fan']: enc_status['fan'] = status

    for temp in temps:
        # there are 14 total for emm, supply top/bottom, and each drawer
        labels = labels = 'name="{}", {}'.format(temp['Name'],common_labels)
        status = mapstatus.get(temp['Status'],2)
        print('enclosure_temp_celsius{{{0}}} {1}'.format(labels, temp['TemperatureCel']))
        print('enclosure_temp_status{{{0}}} {1}'.format(labels, status))
        if status > enc_status['temp']: enc_status['temp'] = status

    for volt in volts:
        labels = labels = 'name="{}", {}'.format(volt['Name'],common_labels)
        status = mapstatus.get(volt['Status'], 2)
        print('enclosure_voltage_status{{{0}}} {1}'.format(labels,status))
        if status > enc_status['volt']: enc_status['volt'] = status
    
        vos = 0
        vus = 0

        if volt['CritOver'] == 'TRUE':
            vos = 2
        elif volt['WarnOver'] == 'TRUE':
            vos = 1

        if volt['CritUnder'] == 'TRUE':
            vus = 2
        elif volt['WarnUnder'] == 'TRUE':
            vus = 1

        print('enclosure_voltage_over_status{{{0}}} {1}'.format(labels,vos))
        print('enclosure_voltage_under_status{{{0}}} {1}'.format(labels,vus))
        # print('enclosure_voltage_millivolts{{{0}}} {1}'.format(labels,volt['Millivolts']))

    # create a total status composite
    # The non-json secli enclosure output includes enclosure status CRIT/WARN but no such key is present in json output
    # the AlarmCount value may reflect some status but in our experience it will be 0 even if a component is showing failed status 
    # the max value of all sub system status will be reflected here
    # A non-zero alarm count also will set a critical status 
    status = max(enc_status.values())  
    print('enclosure_status{{{0}}} {1}'.format(
        common_labels,
        status
        ))



