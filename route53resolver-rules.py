#!/usr/bin/python3
import json
import argparse
import Unbound

parser = argparse.ArgumentParser()
parser.add_argument("-u", "--unbound", type=str,
                    help="Unbound IPs", default='10.78.0.0/16,172.16.0.0/12')
parser.add_argument("-l", "--logging", type=str,
                    help="logging level", default="WARN")
parser.add_argument("-p", "--path", type=str,
                    help="Unbound configurations path", default="unbound")
args = parser.parse_args()

unbound = Unbound.Unbound(args)

print(unbound.unbound_zones())
