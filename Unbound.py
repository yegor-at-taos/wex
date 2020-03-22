#!/usr/bin/env python3
import ipaddress
import os
import re
import logging


class Unbound:
    def __init__(self, args):
        self.args = args

        self.valid_networks = set([
            ipaddress.ip_network(zone)
            for zone
            in args.unbound.split(',')
            ])
        self.route53_domains = [
                '..',  # '.' + trailing dot
                '...'
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
            current_zone = {
                    'forward-addr': set(),
                    'name': None
                    }
            for line in f:
                if line.find(':') == -1:
                    continue
                line = [
                        part.strip()
                        for part in line.split(':')
                        ]
                if line[0] == 'forward-zone':
                    if current_zone['name'] and current_zone['forward-addr']:
                        yield current_zone
                    current_zone = {
                            'forward-addr': set(),
                            'name': None
                            }
                elif line[0] == 'name':
                    temp = re.sub('^["\']*', '', line[1])
                    temp = re.sub('["\']*$', '', temp)  # trim trail
                    temp = re.sub('\\.*$', '', temp)  # trim trail dot if any
                    current_zone['name'] = temp.lower() + '.'  # append dot
                elif line[0] == 'forward-addr':
                    current_zone['forward-addr'].add(
                            ipaddress.ip_address(line[1]))

            # make sure that last zone is reported
            if current_zone['name'] and current_zone['forward-addr']:
                yield current_zone

    def retrieve_all(self):
        self.data = {}
        for name in os.listdir(self.args.path):
            for zone in self.parse_unbound_config(f'{self.args.path}/{name}'):
                if zone['name'] not in self.data:
                    self.data[zone['name']] = set()
                self.data[zone['name']].update(zone['forward-addr'])

    def zones(self):
        value = set()
        # set arithmetic won't work as we have networks vs addresses

        for zone in self.data.items():
            if zone[0] in self.route53_domains:
                continue  # exclude '.', '..', etc.
            for valid in self.valid_networks:
                for forward_addr in zone[1]:
                    if forward_addr in valid:
                        value.add(zone[0])

        return value
