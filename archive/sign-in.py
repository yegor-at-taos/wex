#!/usr/bin/env python3
import re
import json

from html.parser import HTMLParser

class MyHTMLParser(HTMLParser):
    def __init__(self):
        self.flag = False
        self.accounts = dict()

        super().__init__()

    def handle_starttag(self, tag, attrs):
        if tag != 'div' or not attrs:
            return
        for tuple in attrs:
            if tuple[0] == 'class' and tuple[1] == 'saml-account-name':
                self.flag = True
                break

    def handle_data(self, data):
        if not self.flag:
            return

        if not re.match('^Account: wexinc-', data):
            raise ValueError(f'Parse error: {data}')

        data = data[data.find(':') + 9:].split(' ')
        data[1] = re.sub('[()]', '', data[1])

        self.accounts[data[1]] = data[0]

        self.flag = False


parser = MyHTMLParser()

with open('sign-in.html') as f:
    for line in f:
        parser.feed(line)

print(json.dumps(parser.accounts, indent=2))
