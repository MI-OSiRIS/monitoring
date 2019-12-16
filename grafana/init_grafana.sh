#!/bin/bash
INPUT="grafana_conf"
if [  ! -f $INPUT ]; then
    echo "WARNING: No $INPUT found"
    exit
fi
source grafana_conf

if [ -f "conf/wizzy.json" ]
then
    echo "✔ wizzy conf file found"
else
    echo "NOTE: wizzy conf not found so created"
    wizzy init
fi

if [  ! -f .gitignore ]  || ! grep -q "conf/wizzy.json" .gitignore ; then
    echo "Adding conf/wizz.json to .gitignore"
    echo "conf/wizzy.json" >> .gitignore
fi
if [  ! -f .gitignore ]  || ! grep -q "$INPUT" .gitignore ; then
    echo "Adding $INPUT to .gitignore"
    echo "$INPUT" >> .gitignore
fi



id=${ORIGIN%%.*}
id=${id##*//}
wizzy add grafana "$id"
wizzy set grafana envs "$id" url $ORIGIN
if [ ! -z "$USER" ] && [ ! -z "$PASS" ]; then
    wizzy set grafana envs "$id" username $USER
    wizzy set grafana envs "$id" password $PASS
fi
wizzy set context grafana "$id"

read -p "Importing from $ORIGIN as your source. Continue? " yn
case $yn in
    [Yy]* ) ;;
    [Nn]* ) exit;;
    * ) echo "Please answer yes or no.";;
esac

for END_POINT in ${END_POINTS[@]}
do
    id=${END_POINT%%.*}
    id=${id##*//}
    wizzy add grafana "$id"
    wizzy set grafana envs "$id" url $END_POINT
    if [ ! -z "$USER" ] && [ ! -z "$PASS" ]; then
        wizzy set grafana envs "$id" username $USER
        wizzy set grafana envs "$id" password $PASS
    fi
    read -p "Setting $END_POINT as export endpoint. Continue? " yn
    case $yn in
        [Yy]* ) ;;
        [Nn]* ) exit;;
        * ) echo "Please answer yes or no.";;
    esac
    wizzy set context grafana "$id"
done
echo "Running Update Grafana"
./update_grafana.sh

exit




