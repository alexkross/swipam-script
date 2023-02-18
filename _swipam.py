#!/usr/bin/env python
# vim: set fileencoding=utf-8 :
#
# SolarWinds IPAM as an Ansible dynamic inventory
# Designed for huge network topologies.
# (c) <https://github.com/alexkross/swipam-script>
# See also <https://gist.github.com/alexkross/7f80accff12649b940fc9779813b9b91>
#
# This script is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# You should have received a copy of the GNU General Public License
# along with it.  If not, see <http://www.gnu.org/licenses/>.

import sys
assert sys.version_info > (3, 8), "Python 3.8 or newer is required."

import json
import argparse
from os import getenv, path, remove
from functools import partial
from itertools import compress
from ipaddress import ip_address, ip_network
from datetime import datetime
from dateutil.tz import tzlocal
from zipfile import ZipFile, ZIP_DEFLATED

from ansible.module_utils.six.moves import configparser as ConfigParser

# ToDo: parameterize in .ini
sys.path.insert(0, path.join(getenv("HOME"), 'orionsdk'))

try:
    from orionsdk import SwisClient
except ImportError:
    sys.exit("SolarWinds OrionSDK python client is not installed. See https://github.com/solarwinds/orionsdk-python``")

from urllib3 import disable_warnings, exceptions as urllib3exc
disable_warnings(category=urllib3exc.InsecureRequestWarning)

class _SwisClient (SwisClient): # to override proxy settings
    def _req(self, method, frag, data=None):
        resp = self._session.request(method, self.url + frag,
            data=json.dumps(data, default=lambda obj: obj.isoformat() if isinstance(obj, datetime) else None),
            proxies={"http": None, "https": None}, # quick fix to override proxy environment settings if any
            #verify=self._session.verify, headers={'Content-Type': 'application/json'}
        )
        if 400 <= resp.status_code < 600: # try to extract reason from response when request returns error
            try:
                resp.reason = json.loads(resp.text)['Message'];
            except:
                pass;
        resp.raise_for_status()
        return resp

def json_format_dict(data, pretty=False): # Converts a dict to a JSON object and dumps it as a formatted string
    return json.dumps(data, sort_keys=True, indent=2) if pretty else json.dumps(data)

def _to_safe(word): # Converts 'bad' characters in a string to underscores so they can be used as Ansible groups
    return word.replace(' /', '/')

_ipn = partial(ip_network, strict=False)
def _ipn_tree(ns):
    ns.reverse()
    ft = []
    t = {}
    while ns:
        nf = ns.pop()
        for i in range(len(ft)):
            np, st = ft[i]
            if nf.subnet_of(np):
                #assert nf not in st # Debug
                st[nf] = {}
                ft.insert(i, (nf, st[nf]))
                break
        else:
            t[nf] = {}
            ft.append((nf, t[nf]))
    return t

def _ipn_match(ns, t):
    for n in t:
        m = _ipn_match(ns, t[n])
        if m:
            return m
        if ns.subnet_of(n):
            return n

def _root(sup, id):
    return _root(sup, sup[id]) if id in sup else id

name = path.basename(__file__).split('.')[0]
if not name[0].isalpha(): # leading '_' or digit[s] to make special parsing order
    name = name.strip('_1234567890') # Note: from the EOL too.

class Inventory(object):
    def __init__(self):
        self.hv = {}
        self.inv = {
            '_meta': {
                'hostvars': self.hv
            },
            'all': {
                #'children': ['ungrouped'] (see https://github.com/ansible/ansible/issues/45601)
            },
            #'ungrouped': {} # ToDo: remove this empty group cautiously, because it is counted in other places (see https://github.com/ansible/ansible/issues/45601)
        }
        self.idx = {0: (self.inv['all'],)}
        self.session = None   # Requests session
        self.config_path = path.dirname(path.realpath(__file__)) + '/' + name + '.ini'
        if getenv(name.upper()+'_INI_PATH') is not None:
            self.config_paths.append(path.expanduser(path.expandvars(env_value)))
        # ToDo: consider which subset of these attributes should be private

    def _read_settings(self):
        config = ConfigParser.ConfigParser()
        config.read(self.config_path)
        # SolarWinds IPAM API (SWIS) related
        try:
            self.host = config.get(name, 'host')
            self.user = config.get(name, 'user')
            self.password = config.get(name, 'password', raw=True)
            #self.ssl_verify = config.getboolean(name, 'ssl_verify')
        except (ConfigParser.NoOptionError, ConfigParser.NoSectionError) as e:
            print("Error parsing configuration: %s" % e, file=sys.stderr)
            return False
        self.save_raw = config.getboolean(name, 'save_raw', fallback=False)
        # Ansible related
        for par in ['sncols', 'hstcols', 'internal', 'exclude', 'grvars', 'snvars', 'hstvars', 'hstvarmap']:
            s = config.get('ansible', par)
            setattr(self, par, json.loads(config.get('ansible', par).replace("'", '"')))
        self.hstsel = [c in self.hstvars for c in self.hstcols]
        self.snpref = 'SELECT DISTINCT {} FROM IPAM.Subnet ORDER BY Address'.format(', '.join(self.sncols))
        self.hstpref = 'SELECT {} FROM IPAM.IPNode WHERE'.format(', '.join(self.hstcols))
        self.include_root_net = config.get('ansible', 'include_root_net', fallback=False)
        self.include_nets = list(sorted(map(_ipn, json.loads(config.get('ansible', 'include_nets', fallback='[]').replace("'", '"')))))
        self.exclude_nets = list(sorted(map(_ipn, json.loads(config.get('ansible', 'exclude_nets', fallback='[]').replace("'", '"')))))
        # Cache related
        self.swipam_cache_path = path.expanduser(config.get('cache', 'swipam_cache', fallback=path.abspath(path.dirname(self.config_path) + path.sep + path.pardir) + path.sep + name + "-cache.json" ))
        self.local_cache_path = config.get('cache', 'local_cache', fallback=None)
        if self.local_cache_path:
            self.local_cache_path = path.abspath(self.local_cache_path)
        #self.swipam_cache_path_hostcollections = swipam_cache_path<ext removed> + "/%s.hostcollections" % name
        # ToDo: self.swipam_cache_max_age = config.getint('cache', 'max_age', fallback=60)
        #try:
        #    self.scan_new_hosts = config.getboolean('cache', 'scan_new_hosts')
        #except (ConfigParser.NoOptionError, ConfigParser.NoSectionError):
        #    self.scan_new_hosts = False
        return True

    def _parse_cli_args(self): # Command line argument processing
        parser = argparse.ArgumentParser(description='Produce an Ansible Inventory from SolarWinds IPAM and make a cache valid until next day')
        parser.add_argument('--list', action='store_true', default=True, help='List instances (default: True)')
        parser.add_argument('--get-swipam-cache', action='store_true', default=False, help='Get swipam cache file name')
        parser.add_argument('--get-local-cache', action='store_true', default=False, help='Get local cache file name (Is always used if exists. Delete to update.)')
        parser.add_argument('--refresh-cache', action='store_true', default=False, help='Remove "{}" (same as touch "{}")'.format(self.swipam_cache_path, self.config_path))
        self.args = parser.parse_args()

    def _get_session(self):
        if not self.session:
            self.session = _SwisClient(self.host, self.user, self.password)
            #self.session.verify = self.ssl_verify
        return self.session

    def _query_tree(self, per_page=512):
        t = c = s = per_page # to, count, step (const)
        f = 1 # from
        raw = []
        ses = self._get_session()
        while c == s: # Use ``while c:`` if server may produce less results than requested
            res = ses.query(self.snpref + ' WITH ROWS {} TO {}'.format(f, t))
            c = len(res['results'])
            raw.extend(list(r.values()) for r in res['results'])
            f += c
            t = f + s - 1
            #sleep(0.2) # give SWIS some rest
        if self.save_raw: # ToDo: ensure no tab characters on any lines.
            self.raw_file.writestr('_index.tsv', '\n'.join(['\t'.join(map(str, l)) for l in [self.sncols]+raw])+'\n')
        return raw

    def _update_tree(self): # Note: set up some object attributes
        #assert len(self.inv['_meta']) == 1 and len(self.inv['all']) == 1 and len(self.idx) == 1 # with 'ungrouped'
        assert len(self.inv['_meta']) == 1 and not self.inv['all'] and len(self.idx) == 1
        raw = self._query_tree()
        self.subs = [dict(zip(self.sncols, l)) for l in raw]
        for s in filter(lambda s: s['GroupTypeText'] == 'Group' and s['DisplayName'] not in self.exclude, self.subs):
            pid = s['ParentId']
            sid = s['SubnetId']
            n = _to_safe(s['DisplayName'])
            assert n not in self.inv, 'Group name "%s" (from subnet "%s") is not unique!' % (n, s['DisplayName']) # Ansible require unique group names. NOT Debug.
            if sid in self.idx:
                pass
            else:
                self.idx[sid] = {}, {} #``'hosts': []`` in first
            v, i = self.idx[sid] # ansible variables and internal auxiliary data from SWIS
            v['vars'] = {v: s[v] for v in self.grvars}
            i.update({i: s[i] for i in self.internal})
            self.inv[n] = v
            c = self.idx.setdefault(pid, ({'children': []}, {}))[0].setdefault('children', [])
            c.append(n)
        sup = {s['SubnetId']: s['ParentId'] for s in self.subs if s['GroupTypeText'] == 'Supernet'}
        self.sups = {s: _root(sup, p) for s, p in sup.items()}

    def _query_hsts(self, id, per_page=500):
        t = c = s = per_page # to, count, step (const)
        f = 1 # from
        raw = []
        ses = self._get_session()
        while c == s: # Use ``while c:`` if server may produce less results than requested
            res = ses.query(self.hstpref + ' SubnetId={} AND Status<>2 ORDER BY IPAddressN WITH ROWS {} TO {}'.format(id, f, t))['results']
            c = len(res)
            raw.extend(r.values() for r in res)
            f += c
            t = f + s - 1
            #sleep(0.2) # give SWIS some rest
        if self.save_raw: # ToDo: ensure no tab characters on any lines.
            self.raw_file.writestr(str(id)+'.tsv', '\n'.join(['\t'.join(map(str, l)) for l in [self.hstcols]+raw])+'\n')
        return raw

    def _update_hsts(self):
        #sub = {}
        tmp = {}
        assert not any(g.get('hosts') for g in self.inv.values() if g not in ('_meta', 'all')) #assert hasattr(self, 'ipnt')
        #assert len(self.inv['all']['children']) > 1 # with 'ungrouped'
        incl = _ipn_tree(self.include_nets)
        excl = _ipn_tree(self.exclude_nets)
        for s in filter(lambda s: s['GroupTypeText'] == 'Subnet', self.subs):
            p = s['ParentId']
            if p in self.idx.keys() | self.sups.keys(): # sets
                ip = ip_network('/'.join((s['Address'], str(s['CIDR']))))
                # IP network triage
                mexcl = _ipn_match(ip, excl)
                mincl = _ipn_match(ip, incl)
                if not mexcl and not mincl:
                    if not self.include_root_net:
                        continue
                elif mexcl and mincl:
                    if mexcl.subnet_of(mincl):
                        continue
                elif mexcl or not mincl and not self.include_root_net:
                    continue
                id = s['SubnetId']
                p = self.sups.get(p, p)
                v = self.idx[p][0]
                n = _to_safe(s['DisplayName']) # Just a variant (see the notebook).
                assert n not in self.inv, '"' + n + '"' + ' is not unique!'
                hs = []
                self.inv[n] = {'hosts': hs, 'vars': {v: s[v] for v in self.snvars}}
                tmp[id] = self.inv[n], {i: s[i] for i in self.internal}
                c = v.setdefault('children', [])
                c.append(n)
                raw = self._query_hsts(id)
                for l in raw:
                    h = dict(zip(self.hstvars, compress(l, self.hstsel)))
                    ha = h.pop('IPAddress')
                    if ip_address(ha) in (ip.network_address, ip.broadcast_address):
                        continue
                    assert ha not in self.hv, '"' + ha + '"' + ' is not unique!' # Ansible require unique hosts in ``_meta``. NOT Debug.
                    hs.append(ha)
                    h = {self.hstvarmap.get(k, k): v for k, v in h.items() if v}
                    if h: # Functional style (may be faster): ``dict(zip(compress(h.keys(), h.values()), compress(h.values(), h.values())))``.
                        self.hv[ha] = h
        self.idx.update(tmp)

    def run(self):
        # Read settings and parse CLI arguments
        if not self._read_settings():
            return False
        self._parse_cli_args()
        if self.args.get_swipam_cache:
            print(self.swipam_cache_path)
            return True
        if self.args.get_local_cache:
            print(self.local_cache_path)
            return True
        if self.local_cache_path and path.exists(self.local_cache_path):
            with open(self.local_cache_path) as input:
                print(input.read())
            return True
        if path.exists(self.swipam_cache_path):
            tz = tzlocal() # assuming the same place in the universe for every run
            mt = path.getmtime(self.swipam_cache_path)
            if self.args.refresh_cache or path.getmtime(self.config_path) > mt or datetime.fromtimestamp(mt, tz).day != datetime.now(tz).day:
                remove(self.swipam_cache_path)
        try:
            # ToDo: make it a binary and chunked in some size for speed/memory sake, because this JSON line will be huge if not prettyfied.
            with open(self.swipam_cache_path) as input: #+ path.sep + file
                print(input.read())
        except FileNotFoundError:
            if self.save_raw:
                raw_path = self.swipam_cache_path.removesuffix('.json') + '.raw.zip'
                self.raw_file = ZipFile(raw_path, compression=ZIP_DEFLATED, mode='w')
            self._update_tree()
            self._update_hsts()
            if self.save_raw:
                self.raw_file.close()
            assert self.inv['_meta']['hostvars'] == self.hv # Debug
            with open(self.swipam_cache_path, 'w') as output:
                json.dump(self.inv, output)
            json.dump(self.inv, sys.stdout)
            print() # EOL forced
        for a in ('inv', 'idx'): # force single-shot
            delattr(self, a)
        return True

if __name__ == '__main__':
    sys.exit(not Inventory().run())
