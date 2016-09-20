#!/usr/bin/env python
import sys
import os

thisdir = os.path.dirname(os.path.realpath(__file__))
config = {
  'BASE_PATH': thisdir,
  'SLACK_TOKEN': os.environ.get('SLACK_TOKEN'),
  'DEBUG': False
}

import client

bot = client.init(config)
try:
    bot.start()
except KeyboardInterrupt:
    sys.exit(0)
