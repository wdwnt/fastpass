import json
import requests

class SlackMessenger(object):
    def __init__(self, webhook_url=''):
        if not webhook_url:
            self.webhook_url = 'https://hooks.slack.com/services/' \
                               'T0MQRT945/B6EJ999CP/ywQKzU2FHm1q1iUh5DKSVOls'

    def send(self, msg, channel='', username='Bob Chapek Slack Bot',
             icon_emoji=':haha:'):
        icon = icon_emoji
        if not icon.startswith(':'):
            icon = ':' + icon
        if not icon.endswith(':'):
            icon = icon + ':'
        payload = {'text': msg, 'username': username, 'icon_emoji': icon}
        if channel:
            payload['channel'] = channel
        headers = {'Content-Type': 'application/json'}
        resp = requests.post(self.webhook_url, data=json.dumps(payload),
                             headers=headers)
        if resp.status_code != 200:
            raise ValueError(
                'Request to Slack returned an error {}:\n{}'.format(
                    resp.status_code, resp.text)
            )