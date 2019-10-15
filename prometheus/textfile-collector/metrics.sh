#!/bin/bash

# A sample of rolling up various text metric generators in this repository

# Set this for node exporter: --collector.textfile.directory="/var/cache/metrics"
METRICS="/var/cache/metrics"
SCRIPTS="/usr/local/bin"

# CLUSTER should match the names of your prometheus ceph scrape jobs
# so you can group the osdinfo.py output on the cluster label 
CLUSTER='ceph'

RUNMETRICS=('smartinfo.py' 'enclosureinfo.py' 'osdinfo.py' 'diskinfo.sh')

for m in ${RUNMETRICS[@]}; do
    # only osdinfo.py takes the argument, the others just ignore it
    ${SCRIPTS}/${m} ${CLUSTER} > ${METRICS}/${m}.$$
    mv ${METRICS}/${m}.$$  ${METRICS}/${m}.prom
done
