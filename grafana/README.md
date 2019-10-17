Simple scripts to source control and automate grafana configs on multiple servers.
This script controls both dashboards and datasources.

1. Create a git repository
2. Create a grafana_conf file. Within the conf, set username and password.
   Additionally set your origin  and end point servers. The end point
   servers will pull their grafna configurations from the origin. See below
   for an example.
```
USER="username"
PASS="password"
ORIGIN=https://origin.org
END_POINTS=( https://endpoint1.org https://endpoint2.org )
```

3. The first time, within command line run
   ```
   ./init_grafana.sh
   ```

4. To update your end points, within command line run
   ```
   ./update_grafana.sh
   ```
   Note that the script checks if there are any differences from git history
   before updating changes.

5. To commit while updating use the flag -c . If some dashboards are
   giving issues while importing use the flag -d which deletes all end point
   dashboards before exporting.