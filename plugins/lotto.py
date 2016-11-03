from __future__ import unicode_literals
import os
import redis
from client import slack_client as sc
from pytz import utc, timezone
from datetime import datetime, timedelta, time


crontable = []
outputs = []


redis_client = redis.from_url(os.environ.get("REDIS_URL"))


def _parse_env_list(var):
    x = os.environ.get(var, None)
    if x is not None:
        x = x.strip().split(',')
    return x


ALLOWED_CHANNELS = _parse_env_list('ALLOWED_CHANNELS')
ALLOWED_USERS = _parse_env_list('ALLOWED_USERS')

MY_ID = sc.server.users.find(sc.server.username).id
MY_IDENT = '<@%s>' % MY_ID
MY_IDENT_OFFSET = len(MY_IDENT)


class UserState(object):
    ACTIVE_USERS = {}
    ACTIVE_USERS_KEY = "users"
    CACHE_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"

    _utc_last_tick = None
    _utc_last_spoke = None
    _msg = "hasn't bought a lotto ticket today"

    @property
    def msg(self):
        return self._msg

    @msg.setter
    def msg(self, msg):
        self._msg = msg
        redis_client.hset(self.user, 'msg', msg)

    @property
    def utc_last_spoke(self):
        return self._utc_last_spoke

    @utc_last_spoke.setter
    def utc_last_spoke(self, utc_last_spoke):
        self._utc_last_spoke = utc_last_spoke
        redis_client.hset(self.user, 'last_spoke', utc_last_spoke.strftime(self.CACHE_DATE_FORMAT))

    @classmethod
    def track_user(cls, user, channel):
        cls.ACTIVE_USERS[user] = cls(user, channel)
        redis_client.hset(user, 'channel', channel)
        redis_client.sadd(cls.ACTIVE_USERS_KEY, user)

    @classmethod
    def untrack_user(cls, user):
        cls.ACTIVE_USERS.pop(user, None)
        redis_client.srem(cls.ACTIVE_USERS_KEY, user)

    @classmethod
    def load_from_cache(cls):
        for u in redis_client.smembers(cls.ACTIVE_USERS_KEY):
            userhash = redis_client.hgetall(u)
            last_spoke = userhash.get('last_spoke')
            if last_spoke is not None:
                last_spoke = utc.localize(datetime.strptime(last_spoke, cls.CACHE_DATE_FORMAT))
            cls.ACTIVE_USERS[u] = cls(u, userhash['channel'], userhash.get('msg'), last_spoke)
            print cls.ACTIVE_USERS[u]

    def __init__(self, user, channel, msg=None, utc_last_spoke=None):
        self.user = user
        self.channel = channel
        if msg is not None:
            self.msg = msg
        if utc_last_spoke is not None:
            self.utc_last_spoke = utc_last_spoke
        self.time_begin = time(hour=4, minute=0)
        self.time_end = time(hour=11, minute=15)

    def __unicode__(self):
        return ', '.join((self.user, self.channel, self.msg, str(self.utc_last_spoke)))

    def spoke(self):
        self.utc_last_spoke = utc.localize(datetime.utcnow())

    def tick(self):
        utc_now = utc.localize(datetime.utcnow())
        print "Tick", self.user
        print self.user, "self.utc_last_spoke", self.utc_last_spoke, "utc_now", utc_now, "self._utc_last_tick", self._utc_last_tick

        if self._utc_last_tick is not None:
            u = getuser(self.user)
            if u is None:
                UserState.untrack_user(self.user)
                return

            print self.user, u
            tz = u.tz
            if tz is None or tz == "unknown":
                zone = utc
            else:
                zone = timezone(tz)

            print self.user, zone

            # hold on to your pants. date maths lies ahead
            local_now = utc_now.astimezone(zone)
            # get the start/end times in the timezone of the user, as utc
            utc_begin = zone.localize(datetime.combine(local_now, self.time_begin)).astimezone(utc)
            utc_end = zone.localize(datetime.combine(local_now, self.time_end)).astimezone(utc)
            utc_reminder_end = utc_end - timedelta(minutes=15)

            print self.user, u.name, "utc_begin", utc_begin, "utc_end", utc_end
            print self.user, u.name, "utc_now > utc_end", utc_now > utc_end, "self._utc_last_tick <= utc_end", self._utc_last_tick <= utc_end
            if utc_now > utc_reminder_end and self._utc_last_tick <= utc_reminder_end:
                if self.utc_last_spoke is None \
                    or self.utc_last_spoke < utc_begin \
                    or self.utc_last_spoke > utc_reminder_end:
                        _send_message(self.user, "Remember to submit your lotto in the next 15 minutes")
            elif utc_now > utc_end and self._utc_last_tick <= utc_end:
                if self.utc_last_spoke is None \
                    or self.utc_last_spoke < utc_begin \
                    or self.utc_last_spoke > utc_end:
                        _send_message(self.user, self.msg, self.channel)

            print "End tick", self.user, u.name
            print

        self._utc_last_tick = utc_now


def getuser(userid):
    return sc.server.users.find(userid)


def getchannel(channelid):
    return sc.server.channels.find(channelid)


def _allowed(userid, channelid):
    global ALLOWED_USERS, ALLOWED_CHANNELS
    username = getuser(userid).name
    channelname = getchannel(channelid).name

    if ALLOWED_CHANNELS is not None and channelname not in ALLOWED_CHANNELS:
        return False
    if ALLOWED_USERS is not None and username not in ALLOWED_USERS:
        return False

    return True


def _send_message(user_id, message, channel_id=None):
    if channel_id is not None:
        message = "<@%s> %s" % (user_id, message)
    else:
        result = sc.api_call('im.open', user=user_id)
        if "ok" in result and result["ok"]:
            channel_id = result["channel"]["id"]
    if channel_id is not None:
        outputs.append([channel_id, message])


def do_tick():
    for s in UserState.ACTIVE_USERS.values():
        try:
            s.tick()
        except e:
            print e


def slashcommand(user, channel, command):
    if command == 'on':
        UserState.track_user(user, channel)
        _send_message(user, "I'll keep an eye out", channel)
    elif command == 'off':
        UserState.untrack_user(user)
        _send_message(user, 'seeya', channel)
    elif command.startswith('msg '):
        _userstate = UserState.ACTIVE_USERS.get(user)
        if _userstate is not None:
            _userstate.msg = command[4:]
            _send_message(user, "ok, I've changed your message", channel)
    else:
        _send_message(user, "sorry, I didn't understand that", channel)


def process_message(data):
    userid = data.get('user')
    channelid = data.get('channel')

    if _allowed(userid, channelid):
        msg = data.get('text').strip()
        if msg.startswith(MY_IDENT):
            msg = msg[MY_IDENT_OFFSET:].lstrip(' :')
            slashcommand(userid, channelid, msg)
        else:
            user_state = UserState.ACTIVE_USERS.get(userid)
            if user_state is not None:
                user_state.spoke()


UserState.load_from_cache()
crontable.append([10, "do_tick"])

