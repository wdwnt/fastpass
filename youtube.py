import argparse
# import functools
from pprint import pprint
from datetime import datetime, timedelta, timezone

from dateutil.parser import parse
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


class YoutubeBroadcasts(object):
    def __init__(self, client_id, client_secret, refresh_token):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.token_uri = 'https://www.googleapis.com/oauth2/v4/token'
        self.api_service_name = 'youtube'
        self.api_version = 'v3'
        self.service = self._get_authenticated_service()
        self.valid_statuses = ('active', 'upcoming',)
        self.upload_playlist_id = 'UURIVd5Ci1bTQqJB_T4q_Jgg'

    def _get_authenticated_service(self):
        # Authorize the request and store authorization credentials.
        # For oAuth2, a Web Application client needs to be created
        # See https://google-auth.readthedocs.io/en/latest/reference/google.oauth2.credentials.html
        # A token is not required if there is a token_uri and refresh_token

        credentials = Credentials(None, client_id=self.client_id, client_secret=self.client_secret,
                                  token_uri=self.token_uri, refresh_token=self.refresh_token)
        return build(self.api_service_name, self.api_version, credentials=credentials)

    # Retrieve a list of broadcasts with the specified status.
    def list_broadcasts(self, broadcast_status='all', debug=False):
        # print('Broadcasts with status "{}":'.format(broadcast_status))

        max_results = 7 if debug else 50

        list_broadcasts_request = self.service.liveBroadcasts().list(
            broadcastStatus=broadcast_status,
            part='id,snippet,contentDetails,status',
            maxResults=max_results
        )

        result = []
        while list_broadcasts_request:
            list_broadcasts_response = list_broadcasts_request.execute()

            for broadcast in list_broadcasts_response.get('items', []):
                # print('{} ({})'.format(broadcast['snippet']['title'], broadcast['id']))
                result.append(broadcast)

            if debug:
                break

            list_broadcasts_request = self.service.liveBroadcasts().list_next(
                list_broadcasts_request, list_broadcasts_response)
        return result

    def list_uploads(self, last_n_minutes=5, only_unlisted=True):
        upload_request = self.service.playlistItems().list(
            part='snippet,status',
            maxResults=10,
            playlistId=self.upload_playlist_id
        )
        result = []
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=last_n_minutes)
        while upload_request:
            upload_response = upload_request.execute()
            upload_request = self.service.playlistItems().list_next(
                upload_request, upload_response)
            for upload in upload_response.get('items', []):
                if parse(upload['snippet']['publishedAt']) > cutoff:
                    result.append(upload)
                else:
                    upload_request = None
        if only_unlisted:
            return [x for x in result if x['status']['privacyStatus'] == 'unlisted']
        return result

    @staticmethod
    def _live_broadcasts(all_broadcasts):
        return [x for x in all_broadcasts if x['live_status'] in ('live', 'liveStarting')]

    @staticmethod
    def _next_day_upcoming(all_broadcasts):
        today = datetime.now(timezone.utc)
        tomorrow = today + timedelta(days=1)
        return [x for x in all_broadcasts if x['live_status'] in ('created', 'ready')
                and parse(x['air_time']) > today and parse(x['air_time']) < tomorrow]

    @staticmethod
    def _last_completed(all_broadcasts):
        return max(filter(lambda x: x['live_status'] == 'complete', all_broadcasts),
                   key=lambda x: parse(x['air_time']))

    def get_broadcasts(self, show_unlisted=False, debug=False):
        all_broadcasts = []
        # for status in self.valid_statuses:
        for status in ('all',):
            try:
                all_broadcasts.extend(self.list_broadcasts(status, debug=debug))
            except HttpError as e:
                print('An HTTP error {} occurred:\n{}'.format(e.resp.status, e.content))
        all_objs = []
        video_for_id = {}
        for x in all_broadcasts:
            if not show_unlisted and x['status']['privacyStatus'] == 'unlisted':
                continue
            obj = {'air_time': x['snippet']['scheduledStartTime'],
                   'title': x['snippet']['title'],
                   'live_status': x['status']['lifeCycleStatus'],
                   'privacy': x['status']['privacyStatus'], 'id': x['id']}
            video_for_id[x['id']] = x
            all_objs.append(obj)
        if debug:
            return all_objs
        result = {
            'live': self._live_broadcasts(all_objs),
            'upcoming': self._next_day_upcoming(all_objs),
            'completed': self._last_completed(all_objs)
        }
        return result

    def get_unlisted_videos(self, past_n_minutes=5):
        all_uploads = []
        try:
            all_uploads.extend(self.list_uploads(last_n_minutes=past_n_minutes))
        except HttpError as e:
            print('An HTTP error {} occurred:\n{}'.format(e.resp.status, e.content))
        result = []
        for x in all_uploads:
            obj = {'published_at': x['snippet']['publishedAt'],
                   'title': x['snippet']['title'],
                   'id': x['snippet']['resourceId']['videoId'],
                   'privacy': x['status']['privacyStatus']}
            result.append(obj)
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--client-id', help='oAuth Client ID')
    parser.add_argument('--client-secret', help='oAuth Client Secret')
    parser.add_argument('--refresh-token', help='oAuth Refresh Token')
    args = parser.parse_args()

    yb = YoutubeBroadcasts(args.client_id, args.client_secret, args.refresh_token)
    pprint(yb.get_broadcasts(show_unlisted=True, debug=True))
