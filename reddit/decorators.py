# This file is part of reddit_api.
# 
# reddit_api is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# reddit_api is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with reddit_api.  If not, see <http://www.gnu.org/licenses/>.

import time
import warnings

import api_exceptions
import reddit

from settings import WAIT_BETWEEN_CALL_TIME
from urls import urls
from functools import wraps
from urlparse import urljoin

ERROR_MAPPING = {'USER_REQUIRED'  : api_exceptions.NotLoggedInException,
                 'WRONG_PASSWORD' : api_exceptions.InvalidUserPass,
                 'RATELIMIT'      : api_exceptions.RateLimitExceeded,
                 'BAD_CAPTCHA'    : api_exceptions.BadCaptcha}

class require_captcha(object):
    """
    Decorator for methods that require captchas.
    """
    URL = urls["new_captcha"]
    VIEW_URL = urls["view_captcha"]

    def __init__(self, func):
        wraps(func)(self)
        self.func = func
        self.captcha_id = None
        self.captcha = None

    def __get__(self, obj, type=None):
        if obj is None:
            return self
        return self.__class__(self.func.__get__(obj, type))

    def __call__(self, caller, *args, **kwargs):
        do_captcha = False
        while True:
            try:
                if do_captcha:
                    self.get_captcha(caller)
                    kwargs['captcha'] = self.captcha_as_dict
                return self.func(caller, *args, **kwargs)
            except api_exceptions.BadCaptcha:
                do_captcha = True

    @property
    def captcha_as_dict(self):
        return {"iden" : self.captcha_id, "captcha" : self.captcha}

    @property
    def captcha_url(self):
        if self.captcha_id:
            return urljoin(self.VIEW_URL, self.captcha_id + ".png")

    def get_captcha(self, caller):
        # This doesn't support the api_type:json parameter yet
        data = caller._request_json(self.URL, {"renderstyle" : "html"})
        # TODO: fix this, it kills kittens
        self.captcha_id = data["jquery"][-1][-1][-1]
        print "Captcha URL: " + self.captcha_url
        self.captcha = raw_input("Captcha: ")


def require_login(func):
    """A decorator to ensure that a user has logged in before calling the
    function."""
    @wraps(func)
    def login_reqd_func(self, *args, **kwargs):
        if isinstance(self, reddit.Reddit):
            user = self.user
            modhash = self.modhash
        else:
            user = self.reddit_session.user
            modhash = self.reddit_session.modhash

        if user is None or modhash is None:
            raise api_exceptions.NotLoggedInException()
        else:
            return func(self, *args, **kwargs)
    return login_reqd_func

class sleep_after(object):
    """
    A decorator to add to API functions that shouldn't be called too
    rapidly, in order to be nice to the reddit server.

    Every function wrapped with this decorator will use a collective
    last_call_time attribute, so that collectively any one of the funcs won't
    be callable within the WAIT_BETWEEN_CALL_TIME; they'll automatically be
    delayed until the proper duration is reached.
    """
    last_call_time = 0     # init to 0 to always allow the 1st call
    WAIT_BETWEEN_CALL_TIME = WAIT_BETWEEN_CALL_TIME

    def __init__(self, func):
        wraps(func)(self)
        self.func = func

    def __call__(self, *args, **kwargs):
        call_time = time.time()

        since_last_call = call_time - self.last_call_time
        if since_last_call < WAIT_BETWEEN_CALL_TIME:
            time.sleep(WAIT_BETWEEN_CALL_TIME - since_last_call)

        self.__class__.last_call_time = call_time
        return self.func(*args, **kwargs)

def parse_api_json_response(func):
    """Decorator to look at the Reddit API response to an API POST request like
    vote, subscribe, login, etc. Basically, it just looks for certain errors in
    the return string. If it doesn't find one, then it just returns True.
    """
    @wraps(func)
    def error_checked_func(*args, **kwargs):
        return_value = func(*args, **kwargs)
        if isinstance(return_value, dict):
            for k in return_value:
                if k not in ('data', 'kind', 'errors'):
                    # The only jquery response we want to allow is captcha
                    if k == 'jquery':
                        try:
                            assert return_value[k][-2][-1] == 'captcha'
                            continue
                        except:
                            pass
                    warnings.warn("Unknown return value key: %s" % k)
            if 'errors' in return_value and return_value['errors']:
                error_list = []
                for item in return_value['errors']:
                    error, msg, other = item
                    if error in ERROR_MAPPING:
                        error_list.append(ERROR_MAPPING[error](msg))
                    else:
                        error_list.append(Exception('(Unknown) %s: %s (%s)' %
                                                    (errors, msg, other)))
                if len(error_list) == 1:
                    raise error_list[0]
                else:
                    raise api_exceptions.ExceptionList(error_list)
        return return_value
    return error_checked_func