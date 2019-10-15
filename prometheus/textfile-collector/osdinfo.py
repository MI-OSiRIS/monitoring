#!/usr/bin/env python3
#
# Map Data and DB disk devices to Ceph OSD
# Does not require OSD to be started/mounted, uses LV tags to find device information

# Takes a string identifying Ceph cluster as argument (defaults to 'ceph')
# The cluster name will be used to label metrics {cluster='ceph'}

# If you are using the Prometheus ceph exporter this string should correspond to 
# the cluster label you set for that scrape job so the two metrics can be correlated

# sample metric:  ceph_osd_device_info{cluster="ceph", ceph_daemon="osd.835", device="db_mpathat", type="db"} 

# ceph_daemon tag will not be unique as an OSD may have multiple devices
# and devices may have multiple sub-devices all included in the output

# metrics will be produced for the top level device (typically LVM) and for any slave devices 
# there will be another info metric for each device dm- and sdX or nvmeX, etc as reflected in /sys/block/<dev>/slaves/<dev>/slaves 

import argparse
import subprocess
import json
from glob import glob
from os.path import basename, dirname, exists
from os import readlink, path

osdpath = '/var/lib/ceph/osd'

parser = argparse.ArgumentParser(description='Map Data and DB/WAL disk devices to Ceph OSD')
parser.add_argument('cluster', help='Cluster name set in metric label', default='ceph', nargs='?')
args = parser.parse_args()
cluster = args.cluster

series = [ '# HELP ceph_osd_device_info LVM names and physical devices correlated to ceph OSD.  Includes sub-devices for mpath.']

# find devices from LV tags
# returns dictionary { osd_id: { block: device, db: device, wal: device} }
# devices not defined will not have a key defined in the osd dictionary
def get_osd_devices_lvm():
    osdlist = {}
    cmd = ['/sbin/lvs', '-o', 'lv_tags', '--reportformat=json']
    lvs_output = subprocess.check_output(cmd,stderr=subprocess.DEVNULL)
    lv_tags = json.loads(lvs_output)
    
    for lv in lv_tags['report'][0]['lv']:
        # we're only interested in ceph block devices, which will include info on their db/wal devices
        if 'ceph.type=block' not in lv['lv_tags']: 
            continue

        # tags are comma separated string of key-value pairs (which probably should have been JSON encoded)
        taglist = lv['lv_tags'].split(',')
        tagdict = {}
        osd = {}
        for tag in taglist:
            name,value = tag.split('=')
            tagdict[name] = value

        for dt in ['block', 'db', 'wal']:
            tagkey = 'ceph.{}_device'.format(dt)
            if tagkey in tagdict.keys():
                osd[dt] = tagdict[tagkey]

        osdlist[tagdict['ceph.osd_id']] = osd    

    return osdlist

# find devices from symlinks in runtime tmp mnt
# this function is not used but left as an option, it should be interchangeable with the lvm function
# returns dictionary { osd_id: { block: device, db: device, wal: device} }
# devices not defined will not have a key defined in the osd dictionary
def get_osd_devices_mount():
    osdlist = {}

    for osddir in glob(osdpath + '/*-*/'):
        dev = {}
        osd = {}
        try:
            with open(osddir + '/whoami', 'r') as fh:
                osdid = fh.read().rstrip()
        except IOError:
            continue            

        dev['block'] = osddir + '/block'
        dev['db'] = osddir + '/block.db'
        dev['wal'] = osddir + '/block.wal'

        for dt, path in dev.items():
            if not exists(path):
                continue
            osd[dt] = readlink(path)
        
        osdlist[osdid] = osd

    return osdlist

# find all slave devices starting from a list containing 1 device
# list returned will include the original device list
def get_slaves(bd):
    # fetch slaves for last item on list being passed down
    sysfs = '/sys/block/{}/slaves/*'.format(bd[-1])
    for sdev in glob(sysfs):
        bd.append(basename(sdev)) 
        bd = get_slaves(bd)
    return bd
        
osd_dev_list = get_osd_devices_lvm()

for osdid, devs in osd_dev_list.items():
    for dt, path in devs.items():
        labels = 'cluster="{}", ceph_daemon="osd.{}", type="{}"'.format(cluster, osdid, dt)
        
        # logical volume name (strip out /dev/vg path)
        series.append('ceph_osd_device_info{{device="{}", {}}} 1'.format(basename(path), labels))

        # get the dm- device from the LV path symlink  (osd are always LV)
        dm = basename(readlink(path))

        for dev in get_slaves([dm]):
            series.append('ceph_osd_device_info{{device="{}", {}}} 1'
                                    .format(dev, labels))

series.sort()
for s in series:
    print(s)

