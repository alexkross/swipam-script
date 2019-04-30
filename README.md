# swipam-script
Ansible dynamic inventory script (not plugin) for SolarWinds IPAM product (IPAM.Subnet and IPAM.IPNode tables at scale)

If you does not have IPAM, but other SolarWinds product that populate Orion.Nodes table you should look at [solarwinds-ansible-inv script](https://github.com/cbabs/solarwinds-ansible-inv) or forks.

The repository also include an example of constructed plugin script that builds additional host groups based on Comment, MachineType (Vendor), Location, etc fields from IPAM.

To get readable output (dropping verbose groups var) from constructed plugin script use command: ``ansible -m debug -a "msg={{hostvars[inventory_hostname]|dict2items|rejectattr(\"key\", \"eq\", \"groups\")|list|items2dict}}" <group_or_host>``

Although inventory script is not strictly required to follow Ansible module and plugin development rules and convetions, and even may be written not in Python, I hesitate to PR it into ansible/contrib/inventory until I will sure that the code is Python 2.7 compatible. Since the development is conducted out of working time and the current code works well in my environment this may be not very soon. Interested parties are welcome to provide comments or feature requests though.

## Main features

- Cache is daily based. Recache will occurr on any cache file timestamped before midnight.
- 3 options to recache: 1) cli parameter, 2) manual cahe file delete, 3) touching .ini file.
- Adaptive script name to avoid collisions. Leading digit and underscore are removed if used for parsing ordering in a single inventory directory (that is common practice).
- A cache file name and place depends on some factors. Provided CLI parameter to get calculated cache file name.
- Longer prefix match wins during IP-address filter processing for inclued and excluded networks.
- Not only all IPAM groups hierarchy are preserved, but final subnets (not supernets) also become host groups.
- Name mangling is minimal. Currently only ' /' is replaced with '/'. Be aware.
- Works at scale and tested in Python 3.7 environment.

## ToDo list (on demand)

- Linting, Python 2.7 compatibility (backporting), then PR to https://github.com/ansible/ansible/tree/devel/contrib/inventory
- Historical cache (good for change control e.g). Autorotation.
- IPAM groups and subnets may be separated from hosts to different caches. May be useful for huge corporate networks. ``--host`` CLI parameter (not yet implemented).
- Cache expiration may be improved to support multi-timezone controlling nodes (for cross-globe enterprises).
- Get additional and/or custom IPAM attributes from other SWIS table[s].
- Improve cache invalidation and output stream handling.
