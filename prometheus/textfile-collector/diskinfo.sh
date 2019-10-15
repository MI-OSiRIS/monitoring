#!/bin/bash

# associate every block device with human friendly name and mountpoint (mountpoint may be empty string)
lsblk -ln -o KNAME,NAME,MOUNTPOINT | awk -F " " '{print $0}' \
    | while read kname name mp; do
        # skip duplicates (multiple devices associated with one higher level device)
        if [[ $DEVLIST == *"${kname}"* ]]; then continue; fi
        DEVLIST="${DEVLIST} $kname"
        echo "node_disk_info{mountpoint=\"$mp\", devname=\"$name\", device=\"$kname\"} 1"
    done 

# another approach reading only mounted filesystems
# https://github.com/prometheus/node_exporter/issues/885
# awk -F " "  '{if ($3 !~ /cgroup|devtmpfs|devpts|proc|sysfs|rpc_pipefs|debugfs|securityfs|binfmt_misc|fusectl/  ) print $0}' /proc/mounts 2>/dev/null  \
#     | while read dev mp  fstype mntopts fs_freq fs_passno ; do
#         if [ -e $dev ] ; then
#             id="$(printf "%d:%d" $(stat -L  -c "0x%t 0x%T" "$dev"))"
#             kname="$(basename $(dirname $(grep -lx "$id" /sys/block/*/dev /sys/block/*/*/dev)))"
#             # strip off the /dev/ part
#             sdev=${dev##/*/}
#             echo "node_disk_info{mountpoint=\"$mp\", devname=\"$sdev\", device=\"$kname\"} 1"
#         fi;
#         done > ${METRICS}/node_disk_info.$$
#         mv ${METRICS}/node_disk_info.$$ ${METRICS}/node_disk_info.prom
