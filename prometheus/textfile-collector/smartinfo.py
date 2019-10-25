#!/usr/bin/env python3
#
# collect SMART info from SATA,SSD, NVMe, and SCSI disks and output prometheus series.
#
# smart_disk_status
# Status indicator from 0 - 2:  0 = OK, 1 = WARN, 2 = FAIL
# Setting is based on bits set in return code from smartctl (see Return Values section of man page: https://linux.die.net/man/8/smartctl)

# smart_disk_attr_total:
# various raw attributes which we hope are 0 or at least should not be rapidly increasing.  
#
# smart_disk_lifetime_percent:  
# NVMe/SSD devices only, percentage lifetime remaining based on attributes which may vary by manufacturer
# We check and use first available of: 'Percent_Life_Remaining', 'Media_Wearout_Indicator', 'Wear_Leveling_Count', 'Unused_Rsvd_Blk_Cnt_Tot'
# 
# smart_disk_temperature_celsius:
# Temperature of disk.  SMART should trip if the temp goes too high but it may be useful to know the specific value for 
# NVMe disks which may throttle at higher temperatures.  
#
# smart_disk_info:  Disk metadata
# smart_disk_info{device="/dev/nvme3", serial="ABC123", model="Dell Express Flash NVMe SM1715 800GB SFF", firmware="IPV0AD3Q"}
#
# Output labels do not necessarily match the names of SMART attributes.
#
# scsi_grown_defect_list is mapped to smart_disk_attr_total{name='reallocated_sector_count'} since they are the same thing
#
# scsi_error_counter_log total_uncorrected_errors for read/write/verify are summed and mapped to 
# smart_disk_attr_total{name='uncorrectable_error_cnt'} (which matches the ATA attribute)

import subprocess

import subprocess
import os.path
import json
import sys

cli = '/sbin/smartctl'


if not os.path.isfile(cli):
    sys.exit(1)

mapcmd = {
    'list': '--scan-open',
    'disk': '--all'
}


return_mask_bits = {
    1: 2,  # device open failed, or command failed, status returned disk failing
    2: 99,  # bad smart data structure (likely SMART not supported), skip disk
    3: 2, # smart status returned FAILURE
    4: 1, # prefail attributes exceed threshold
    5: 0,  # prefail attributes exceeded threshold in the past (may be nothing, does not trip failure status, ignore)
    6: 0,  # device log contains record of errors (may be nothing, does not trip failure status, ignore)
    7: 2,  # DST log contains record of errors
}

# fetch data using command from cli var and return an array of dictionaries as decoded from the JSON results
def fetch_data(query,disk=None, type=None):
    cmd = [cli, '--json', mapcmd[query]]
    if query == 'disk':
        cmd = cmd + [ disk ]
    if type:
        cmd = cmd + [ '-d', type ]

    p = subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    output = p.stdout
 
    # smartctl will return exit status and error message as json and we'll handle it appropriately
    return json.loads(output)
  

# collect serials and avoid duplicate outputs (multipath devices)
serials = []

# collect ssd life counters and pick preferred one to use for lifetime metric
# the two brands I looked at (Intel, Samsung) both have the unused_rsvd counter but have one of the preceding ones as well
# my guess is that many brands will have the unused_rsvd attribute at least, but we'd prefer the others if available
life_counters = ('Percent_Life_Remaining', 'Media_Wearout_Indicator', 'Wear_Leveling_Count', 'Unused_Rsvd_Blk_Cnt_Tot')
# to be used to collect counters found on a given device
device_life_counters = {}


# output series
series = {}
series['info'] = ['# HELP smart_disk_info Disk model, serial, etc as series labels']
series['life'] = ['# HELP smart_disk_lifetime_percent Lifetime remaining for SSD or NVMe devices as percentage from 100 to 0']
series['raw'] = ['# HELP smart_disk_attr_total Raw values for attributes which may indicate disk pre-failure if non-zero or increasing rapidly']
series['temp'] = ['# HELP smart_disk_temperature_celsius Disk temperatures']
series['status'] = ['# HELP smart_disk_status Disk status mapped from smart return value.  0 = OK, 1 = WARN, 2=FAIL']

disks = fetch_data('list')

for disk in disks['devices']:

    # virtual disk open will fail and the error will say something like 'try -d sat+megaraid,24'
    # I'm assuming that other hybrid types may generate the same issue
    # If this is some other disk that should work but somehow fails to open we'd like to catch that and output a critical status
    if 'open_error' in disk.keys() and '-d' in disk['open_error']:
        continue
        
    sminfo = fetch_data('disk', disk['name'], disk['type'])

    # this applies only to nvme devices, others are empty string
    namespaces = [ '' ]

    # devices with a lifetime related attribute will define this later
    lifetime = None

    # to be set from different stats indicating uncorrectable media errors
    total_unc = 0

    # at least one SATA device out there does not define the temperature attribute so we won't output in that case 
    temperature = None

    # multipath devices will occur twice
    if sminfo['serial_number'] in serials:
        continue
    serials.append(sminfo['serial_number'])
    
    rc = sminfo['smartctl']['exit_status']
    if rc == 1:
        for msg in sminfo['smartctl']['messages']:
            print("Error in CLI {}: {}".format(msg['severity'], msg['string']))
        sys.exit(1)

    status = 0 
    for bit in range(1,8):
        if (2**bit & rc) > 0:  # bit is set
            # print("bit {} set".format(bit))
            # hybrid types like sat+megaraid may set bit 2 (smart or other ata command failed) - ignore it
            # they still report smart status and info
            if '+' in disk['type'] and bit == 2:
                continue

            # set the highest (worst) status that matches 
            if return_mask_bits[bit] > status:
                status = return_mask_bits[bit]
                # print("setting status {}".format(bit))

    # problem with SMART output, skip this disk (on my device it means that SMART is unsupported, this may not be universally true)
    if status == 99:
        continue

    if ',' in disk['type']:
        # looking for types like megaraid,1 or sat+megaraid,1.  Convention may not work universally.    
        # (2nd field is the controller disk identifier like [megaraid_disk_23], then strip off the brackets)
        device = sminfo['device']['info_name'].split()[1][1:-1]
    else:
        device = sminfo['device']['name'].replace('/dev/', '')
                
    serial = sminfo['serial_number']

    # fields may vary by device type
    model = ''
    for mdl in ['product', 'model_name']:
        if mdl in sminfo:
            model = sminfo[mdl]

    firmware = ''
    for fw in [ 'revision', 'firmware_version']:
        if fw in sminfo:
            firmware = sminfo[fw]

    # sata SSD or HDD
    if ('sat' in disk['type']):
        for attr in sminfo['ata_smart_attributes']['table']:
            # raw attribute counters
            if attr['name'] in ('Offline_Uncorrectable', 
                        'Current_Pending_Sector_Count', 
                        'Command_Timeout', 
                        'Reported_Uncorrectable_Errors'):
                series['raw'].append('smart_disk_attr_total{{name="{}", device="{}"}} {}'
                    .format(attr['name'].lower(), device, attr['raw']['value']))
            
            # set a var for consistency with other device types which we map onto the same name
            if attr['name'] == 'Uncorrectable_Error_Cnt':
                total_unc = attr['raw']['value']

            if attr['name'] == 'Temperature_Celsius':
                temperature = attr['value']

            if attr['name'] in life_counters:
                device_life_counters[attr['name']] = attr['value']
        
        # set lifetime series depending on available attributes in order of preference
        for lc in life_counters:
                if lc in device_life_counters:
                    lifetime = device_life_counters[lc]
                    break

    if disk['type'] == 'scsi':
        temperature = sminfo['temperature']['current']
        # map grown defects to similar ATA attribute 
        series['raw'].append('smart_disk_attr_total{{name="{}", device="{}"}} {}'.format('reallocated_sector_count', device, sminfo['scsi_grown_defect_list']))
        # troubleshooting
        # print("{}, {}".format(device, model))

        # sum all these into the same attribute used for SATA disks, seems spiritually the same thing
        for eclog in ['read', 'write', 'verify']:
            # not all of these are assured to be in the data structure (SEAGATE ST8000NM0185 doesn't have it, but other Seagate and HGST do have it)
            if eclog in sminfo['scsi_error_counter_log']:
                value = sminfo['scsi_error_counter_log'][eclog]['total_uncorrected_errors']
                total_unc = value + total_unc
            
    if disk['type'] == 'nvme':
        nvmelog = sminfo['nvme_smart_health_information_log']
        temperature = sminfo['temperature']['current']
        total_unc = nvmelog['media_errors']
        lifetime = nvmelog['available_spare']

        namespaces = map(lambda x: 'n{}'.format(x['id']), sminfo['nvme_namespaces'])
        # nvme devices can have multiple namespaces - we would like to have a metric for each one so it can be correlated to
        # other metrics which use the full /dev/nvme0n1 addressing (pretty much everything else)
        # it doesn't make sense to scan each namespace separately - they all refer to the same hardware
        # we'll duplicate the metrics for each namespace in the device
        # Most devs (all that we own) have just 1 namespace so it works out to the same number of series
    
    # try to keep the output as commonly defined as possible, accounting for nvme namespaces
    # smart_disk_attr_total is also appended to output separately for some ATA and SCSI stats
    # for everything else this is the only place it is appended
    for ns in namespaces:
        nsdevice = device + ns

        if lifetime:
            series['life'].append('smart_disk_lifetime_percent{{device="{}"}} {}'.format(nsdevice, lifetime))
        series['raw'].append('smart_disk_attr_total{{name="{}", device="{}"}} {}'.format('uncorrectable_error_cnt', nsdevice, total_unc)) 
        series['status'].append('smart_disk_status{{device="{}"}} {}'.format(nsdevice,status))
        series['info'].append('smart_disk_info{{device="{}", serial="{}", model="{}", firmware="{}"}} 1'
            .format(nsdevice,serial,model,firmware))
        if temperature:
            series['temp'].append('smart_disk_temperature_celsius{{device="{}"}} {}'.format(nsdevice,temperature))
    
for s in ['status', 'info', 'life', 'raw', 'temp']:
    series[s].sort()
    for v in series[s]:
        print(v)



