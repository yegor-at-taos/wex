#!/usr/bin/env python3
import argparse
import ipaddress
import json
import os
import re
import logging


class Unbound:
    def __init__(self, args):
        self.args = args

        self.valid_networks = [
                ipaddress.ip_network('10.78.0.0/16'),
                ipaddress.ip_network('172.16.0.0/12'),
                ]
        self.route53_domains = [
                ".."
                ]
        self.logger = logging.getLogger('Unbound')
        self.logger.setLevel(self.args.logging)

        ch = logging.StreamHandler()
        ch.setLevel(self.args.logging)

        formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)

        self.logger.addHandler(ch)

        self.retrieve_all()

    def parse_unbound_config(self, name):
        self.logger.info(f'Loading UNBOUND config {name}')
        with open(name) as f:
            current = dict()
            for line in f:
                line = line.rstrip()
                if re.match('^forward-zone:$', line):
                    yield current
                    current.clear()
                elif re.match('^\\s+name:\\s', line):
                    line = re.sub('^\\s+name:\\s+', '', line).strip()
                    line = re.sub('^["\']*', '', line)  # trim lead quotation
                    line = re.sub('["\']*$', '', line)  # trim trail quotation
                    current['name'] = line.lower() + '.'
                elif re.match('^\\s+forward-addr:\\s', line):
                    if 'forward-addr' not in current:
                        current['forward-addr'] = dict()
                    addr = line.split(':')[1].strip()

                    for network in self.valid_networks:
                        if ipaddress.ip_address(addr) in network:
                            current['forward-addr'][addr] = None
            yield current

    def retrieve_all(self):
        self.data = {}
        for name in os.listdir(self.args.path):
            for zone in self.parse_unbound_config(f'{self.args.path}/{name}'):
                if not zone:
                    continue
                if 'forward-addr' not in zone:
                    continue
                if 'name' not in zone:
                    continue
                if zone['name'] not in self.data:
                    self.data[zone['name']] = dict()
                self.data[zone['name']].update(zone['forward-addr'])

        # cleanup legacy IPs; only keep 172.16.0.0/12 etc.
        for key in list(self.data.keys()):
            if not self.data[key] or key in self.route53_domains:
                del self.data[key]
