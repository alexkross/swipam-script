# swipam-script - Ansible dynamic inventory script (not plugin) for SolarWinds IPAM (IPAM.Subnet and IPAM.IPNode tables at scale)

Updated on Feb, 2023.

If you does not have IPAM, but other SolarWinds product that populate Orion.Nodes table you should look at [solarwinds-ansible-inv script](https://github.com/cbabs/solarwinds-ansible-inv) or forks.

The repository also includes an example of constructed plugin script that builds additional host groups based on Comment, MachineType (Vendor), Location, etc fields from IPAM.

To get readable output (dropping verbose groups var) from constructed plugin script use command: ``ansible -m debug -a "msg={{hostvars[inventory_hostname]|dict2items|rejectattr(\"key\", \"eq\", \"groups\")|list|items2dict}}" <group_or_host>``

Intended to run daily. Although collection from IPAM is pretty fast, Ansible is very slow in making goups with advanced plugins. To make the inventory run instantly you can use the following aliases:

```bash
hosts_inventory () if [[ -f hosts.toml ]]; then echo --inventory hosts.toml; fi
alias ansible-inventory='ansible-inventory --graph --playbook-dir . $(hosts_inventory)' #--vars is too verbose when facts are collected
alias ansible='ansible --playbook-dir . $(hosts_inventory)'
alias ansible-playbook='ansible-playbook $(hosts_inventory)'
```

Although inventory script is not strictly required to follow Ansible module and plugin development rules and convetions, and even may be written not in Python, I hesitate to PR it into ansible/contrib/inventory for some reasons.

The current code works well in my environment for more than 4 years (as of time of current commit). That said and because the development is conducted out of working time, the code is provided as is without warranty of any kind. Interested parties are welcome to provide comments or feature requests though.

## Main features

- SwisClient class adjusted to override outside proxy settings for direct connection.
- Cache is daily based. Recache will occurr on any cache file timestamped before midnight.
- 3 options to recache: 1) cli parameter, 2) manual cahe file delete, 3) touching .ini file.
- Adaptive script name to avoid collisions. Leading digit and underscore are removed if used for parsing ordering in a single inventory directory (that is common practice).
- A cache file name and place depends on some factors. Provided CLI parameter to get calculated cache file name.
- Longer prefix match wins during IP-address filter processing for inclued and excluded networks.
- Not only all IPAM groups hierarchy are preserved, but final subnets (not supernets) also become host groups.
- Name mangling is minimal. Currently only ' /' is replaced with '/'. Be aware.
- Works at scale and tested in Python 3.7 environment.
- Zipped backup of pulled subnet along with index.

## ToDo list (on demand)

- Linting, Python 2.7 compatibility (backporting), then PR to https://github.com/ansible/ansible/tree/devel/contrib/inventory
- Historical cache (good for change control e.g). Autorotation.
- IPAM groups and subnets may be separated from hosts to different caches. May be useful for huge corporate networks. ``--host`` CLI parameter (not yet implemented).
- Cache expiration may be improved to support multi-timezone controlling nodes (for cross-globe enterprises).
- Get additional and/or custom IPAM attributes from other SWIS table[s].
- Improve cache invalidation and output stream handling.

## See also

- [Random network IP-address generator, fast IP-network tree builder and long prefix match (LPM) function](https://gist.github.com/alexkross/7f80accff12649b940fc9779813b9b91)
