#!/bin/bash

if [ ! -f "conf/wizzy.json" ]; then
    echo "NOTE: wizzy conf not found. Run init script."
    exit
fi

INPUT="grafana_conf"
if [  ! -f $INPUT ]; then
    echo "WARNING: No $INPUT found"
    exit
fi
source grafana_conf

del=false
com=false

if [ "$#" -ne 0 ]; then
    for i in $@
    do
        if [ $i == "-d" ]; then
            del=true
            echo "Hi"
        fi
        if [ $i == "-c" ]; then
            com=true
        fi
    done
fi


if ! git status --porcelain | grep .; then
    echo "No changes"
    if [ del=false ]; then
        exit
    fi
fi

if [ "$com" = true ]; then
    echo "Commiting"
    git add .
    git commit -m "grafana dashboard update auto commit"
    git push
fi

if [ "$del" = true ]; then
    for END_POINT in ${END_POINTS[@]}
    do
        echo "Importing and deleting dashboards at $END_POINT"
        id=${END_POINT%%.*}
        id=${id##*//}
        wizzy set context grafana "$id"
        wizzy import dashboards
        SLUGS=$(wizzy list dashboards | sed '/   │ /!d;s//&\n/;s/.*\n//;:a;/   /bb;$!{n;ba};:b;s//\n&/;P;D')
        for SLUG in $SLUGS;
        do
            wizzy delete dashboard $SLUG
        done
    done
fi

id=${ORIGIN%%.*}
id=${id##*//}
wizzy set context grafana "$id"
rm -rf dashboards
wizzy import dashboards
wizzy import datasources


for END_POINT in ${END_POINTS[@]}
do
    id=${END_POINT%%.*}
    id=${id##*//}
    wizzy set context grafana "$id"
    wizzy export dashboards
    wizzy export datasources
done
exit

