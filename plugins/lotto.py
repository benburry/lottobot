from __future__ import unicode_literals
import os
from client import slack_client as sc
from pytz import utc, timezone
from datetime import datetime


crontable = []
outputs = []


def _parse_env_list(var):
    x = os.environ.get(var, None)
    if x is not None:
        x = x.strip().split(',')


ALLOWED_CHANNELS = _parse_env_list('ALLOWED_CHANNELS')
ALLOWED_USERS = _parse_env_list('ALLOWED_USERS')

USER_STATE = {}
MY_ID = sc.server.users.find(sc.server.username).id
MY_IDENT = '<@%s> ' % MY_ID
MY_IDENT_OFFSET = len(MY_IDENT)


class UserState(object):
    _listening = False
    has_spoken = True
    msg = "hasn't bought a lotto ticket today"

    def __init__(self, user, channel):
        self.user = user
        tz = getuser(user).tz
        if tz == "unknown":
            self.zone = utc
        else:
            self.zone = timezone(tz)
        self.channel = channel
        self.begin = self.zone.localize(datetime.utcnow().replace(hour=4, minute=0, second=0, microsecond=0))
        self.end = self.zone.localize(datetime.utcnow().replace(hour=11, minute=15, second=0, microsecond=0))

    def tick(self):
        now = utc.localize(datetime.utcnow())
        if now > self.begin and now < self.end and not self._listening:
            print now, "Entered listening state"
            self._listening = True
            self.has_spoken = False
        elif now > self.end and self._listening:
            print now, "Exited listening state"
            self._listening = False
            if not self.has_spoken:
                print now, "Hadn't spoken"
                _send_message(self.channel, "<@%s> %s" % (self.user, self.msg,))


def getuser(userid):
    return sc.server.users.find(userid)


def getchannel(channelid):
    return sc.server.channels.find(channelid)


def _allowed(userid, channelid):
    global ALLOWED_USERS, ALLOWED_CHANNELS
    username = getuser(userid).name
    channelname = getchannel(channelid).name

    print username, channelname
    print ALLOWED_USERS, ALLOWED_CHANNELS

    if ALLOWED_CHANNELS is not None and channelname not in ALLOWED_CHANNELS:
        return False
    if ALLOWED_USERS is not None and username not in ALLOWED_USERS:
        return False

    return True


def _send_message(channel_id, message):
    outputs.append([channel_id, message])


def do_tick():
    for s in USER_STATE.values():
        s.tick()


def slashcommand(user, channel, command):
    if command == 'on':
        USER_STATE[user] = UserState(user, channel)
        _send_message(channel, "<@%s> I'll keep an eye out" % user)
    elif command == 'off':
        USER_STATE.pop(user, None)
        _send_message(channel, '<@%s> seeya' % user)
    elif command.startswith('msg '):
        _userstate = USER_STATE.get(user)
        if _userstate is not None:
            _userstate.msg = command[4:]
            _send_message(channel, "<@%s> ok, I've changed your message" % user)
    else:
        _send_message(channel, "<@%s> sorry, I didn't understand that" % user)


def process_message(data):
    userid = data.get('user')
    channelid = data.get('channel')

    if _allowed(userid, channelid):
        msg = data.get('text').strip()
        if msg.startswith(MY_IDENT):
            slashcommand(userid, channelid, msg[MY_IDENT_OFFSET:])
        else:
            user_state = USER_STATE.get(userid)
            if user_state is not None:
                user_state.has_spoken = True


crontable.append([10, "do_tick"])

