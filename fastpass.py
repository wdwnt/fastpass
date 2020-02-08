# import time

import os
from datetime import datetime, timedelta, timezone
from dateutil import parser
import html
import json
import subprocess
from urllib.parse import urlparse

import requests
import redis
from ftfy import fix_text
from flask import Flask, jsonify, request
from jinja2 import Environment, PackageLoader
from flask_cors import CORS
from bs4 import BeautifulSoup

from youtube import YoutubeBroadcasts
from slack import SlackMessenger


def _setup_appflags():
    url = 'https://wdwnt.com/wp-json/wp/v2/appflag'
    try:
        response = requests.get(url, headers=WP_HEADER)
        response_data = response.json()
        result = dict([(x['id'], x['slug']) for x in response_data])
        return result
    except Exception:
        return {}


CACHE_EXPIRE_SECONDS = os.getenv('FASTPASS_CACHE_EXPIRE_SECONDS', 180)
CACHE_SYSTEM = os.getenv('FASTPASS_CACHE_SYSTEM', 'memory')
SERVER_PORT = os.getenv('FASTPASS_HOST_PORT', 5000)
POSTS_PER_PAGE = os.getenv('FASTPASS_POSTS_PER_PAGE', 30)
YOUTUBE_VIDS_PER_PAGE = os.getenv('FASTPASS_YOUTUBE_VIDS_PER_PAGE', 30)
YOUTUBE_API_KEY = os.getenv('FASTPASS_YOUTUBE_API_KEY', None)
YOUTUBE_PLAYLIST_ID = os.getenv('FASTPASS_YOUTUBE_PLAYLIST_ID', None)
YOUTUBE_EXPIRE_SECONDS = os.getenv('FASTPASS_YOUTUBE_EXPIRE_SECONDS', CACHE_EXPIRE_SECONDS)
YOUTUBE_THUMBNAIL_QUALITY = os.getenv('FASTPASS_YOUTUBE_THUMBNAIL_QUALITY', 'default')
BROADCAST_CLIENT_ID = os.getenv('FASTPASS_BROADCAST_CLIENT_ID', None)
BROADCAST_CLIENT_SECRET = os.getenv('FASTPASS_BROADCAST_CLIENT_SECRET', None)
BROADCAST_REFRESH_TOKEN = os.getenv('FASTPASS_BROADCAST_REFRESH_TOKEN', None)
BROADCAST_EXPIRE_SECONDS = os.getenv('FASTPASS_BROADCAST_EXPIRE_SECONDS', 600)
UNLISTED_VIDEO_EXPIRE_SECONDS = os.getenv('FASTPASS_UNLISTED_VIDEO_EXPIRE_SECONDS', 300)
REDIS_HOST = os.getenv('FASTPASS_REDIS_HOST', '127.0.0.1')
REDIS_PORT = os.getenv('FASTPASS_REDIS_PORT', 36379)
REDIS_PASSWORD = os.getenv('FASTPASS_REDIS_PASSWORD', '')
REDIS_USE_SSL = os.getenv('FASTPASS_REDIS_USE_SSL', False)
GIT_COMMIT = os.getenv('HEROKU_SLUG_COMMIT', None)
GIT_RELEASE_AT = os.getenv('HEROKU_RELEASE_CREATED_AT', None)
GIT_DESCRIPTION = os.getenv('HEROKU_SLUG_DESCRIPTION', None)
WP_HEADER = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/50.0.2661.102 Safari/537.36'}
WP_APPFLAGS = _setup_appflags()

app = Flask(__name__, static_folder='static/')
CORS(app)
err_env = Environment(loader=PackageLoader('fastpass', 'error_responses'))
err_env.filters['jsonify'] = json.dumps

mem_cache = {}
redis_db = redis.StrictRedis(host=REDIS_HOST,
                             port=REDIS_PORT,
                             password=REDIS_PASSWORD,
                             ssl=REDIS_USE_SSL)


def format_airtime(in_data):
    result = {'current': {}, 'currentShow': [], 'next': {}}
    for field in ('ends', 'type'):
        result['current'][field] = in_data.get('current', {}).get(field)
    for song in ('current', 'next'):
        md_block = {}
        for field in ('track_title', 'artist_name', 'length'):
            raw_text = in_data.get(song, {}).get('metadata', {}).get(field)
            md_block[field] = fix_text(raw_text) if raw_text else raw_text
        result[song]['metadata'] = md_block
    if len(in_data.get('currentShow', [])):
        show_data = in_data['currentShow'][0]
        show_block = {}
        for field in ('name', 'image_path'):
            raw_text = show_data.get(field)
            show_block[field] = fix_text(raw_text) if raw_text else raw_text
        result['currentShow'].append(show_block)

    return result


def format_live365(in_data):
    result = {'current-track': {}, 'last-played': []}
    track_fields = ('start', 'end', 'artist', 'title', 'art', 'duration', 'sync_offset')
    for field in track_fields:
        result['current-track'][field] = in_data.get('current-track', {}).get(field)
    for song in in_data.get('last-played', []):
        song_data = {}
        for field in track_fields:
            song_data[field] = song.get(field)
        result['last-played'].append(song_data)
    result['stream-urls'] = in_data.get('stream-urls', [])
    result['live_dj_on'] = in_data.get('live_dj_on', False)
    result['listeners'] = in_data.get('listeners', 0)

    return result


def format_wp(in_data, with_content=False, with_player=True):
    result = []
    for post in in_data:
        raw_url = urlparse(post.get('guid', {}).get('rendered', ''))
        obj = dict(author={})
        obj['id'] = post.get('id')
        obj['short_URL'] = 'https://{}/?p={}'.format(raw_url.netloc, obj['id'])
        obj['title'] = html.unescape(post.get('title', {}).get('rendered', ''))
        obj['date'] = post.get('date_gmt')
        authors = post.get('_embedded', {}).get('author', [])
        obj['author']['name'] = ','.join([x.get('name') for x in authors])

        media = post.get('_embedded', {}).get('wp:featuredmedia', [])
        if media:
            obj['featured_image'] = media[0].get('source_url')
        else:
            obj['featured_image'] = ''

        term = post.get('_embedded', {}).get('wp:term', [])
        if term:
            try:
                term_val = term[0][0].get('name', '')
                obj['category'] = html.unescape(term_val)
            except KeyError:
                obj['category'] = ''
        else:
            obj['category'] = ''

        if with_content:
            raw_content = post.get('content', {}).get('rendered', '')
            if with_player:
                obj['content'] = raw_content
            else:
                content, media_url = remove_player(raw_content)
                obj['content'] = content
                obj['media_url'] = media_url
        result.append(obj)
    return result


def remove_player(wp_content):
    soup = BeautifulSoup(wp_content, "html.parser")

    download_url = soup.find('a', class_='powerpress_link_d').get('href', '')
    for tag in soup.select('div.powerpress_player'):
        tag.decompose()
    for tag in soup.select('p.powerpress_links'):
        tag.decompose()
    return str(soup), download_url


def format_wp_single_post(in_data, with_player=True, with_icon=False):
    obj = dict(author=[])
    obj['id'] = in_data.get('id')
    obj['title'] = html.unescape(in_data.get('title', {}).get('rendered', ''))
    term = in_data.get('_embedded', {}).get('wp:term', [])
    if term:
        try:
            term_val = term[0][0].get('name', '')
            obj['category'] = html.unescape(term_val)
        except (KeyError, IndexError):
            obj['category'] = ''
    else:
        obj['category'] = ''
    obj['date'] = in_data.get('date_gmt')

    raw_text = in_data.get('content', {}).get('rendered', '')
    if with_player:
        obj['text'] = raw_text
    else:
        content, media_url = remove_player(raw_text)
        obj['text'] = content
        obj['media_url'] = media_url

    media = in_data.get('_embedded', {}).get('wp:featuredmedia', [])
    if media:
        obj['featured_image'] = media[0].get('source_url')
    else:
        obj['featured_image'] = ''

    authors = in_data.get('_embedded', {}).get('author', [])
    author_list = []
    for x in authors:
        author_data = {'avatar_urls': {}}
        for f in ('id', 'name', 'description'):
            author_data[f] = x.get(f)
        author_data['avatar_urls']['96'] = x.get('avatar_urls', {}).get('96')
        author_list.append(author_data)
    obj['author'] = author_list

    if with_icon:
        app_menu_icon = in_data.get('acf', {}).get('app_menu_icon', '')
        obj['acf'] = {'app_menu_icon': app_menu_icon}

    jrps = in_data.get('jetpack-related-posts', [])
    jrp_list = []
    for x in jrps:
        jrp_data = {}
        for f in ('id', 'title', 'img'):
            jrp_data[f] = x.get(f)
        jrp_list.append(jrp_data)
    obj['jetpack-related-posts'] = jrp_list
    return obj


def format_notifications(in_data):
    result = []
    for n in in_data:
        note_obj = {}
        for x in ('id', 'type', 'date'):
            f = 'date_gmt' if x == 'date' else x
            note_obj[x] = n.get(f)
        for x in ('title', 'text'):
            f = 'excerpt' if x == 'text' else x
            note_obj[x] = html.unescape(n.get(f, {}).get('rendered', '')),
        for x in ('app_notification_category', 'app_notification_type'):
            note_obj[x] = n.get(x, [])
        result.append(note_obj)
    return result


def format_youtube(in_data):
    tnq = YOUTUBE_THUMBNAIL_QUALITY
    result = {'items': [], 'nextPageToken': in_data.get('nextPageToken'),
              'prevPageToken': in_data.get('prevPageToken')}
    for x in in_data.get('items', []):
        obj = dict(snippet=dict(resourceId={}, thumbnails={'default': {}}))
        obj['snippet']['resourceId']['videoId'] = \
            x.get('snippet', {}).get('resourceId', {}).get('videoId')
        obj['snippet']['thumbnails']['default']['url'] = \
            x.get('snippet', {}).get('thumbnails', {}).get(tnq, {}).get('url')
        obj['snippet']['title'] = x.get('snippet', {}).get('title')
        result['items'].append(obj)
    return result


def _store_in_cache(url, data, expire_time=None,
                    expire_seconds=CACHE_EXPIRE_SECONDS):
    if not expire_time:
        expiry = datetime.utcnow() + timedelta(seconds=expire_seconds)
        expiry = expiry.replace(tzinfo=timezone.utc)
    else:
        expiry = expire_time

    if CACHE_SYSTEM == 'redis':
        redis_db.set(url, data, expire_seconds)
    else:
        val = {
            'data': data,
            'expire_at': expiry.timestamp(),
        }
        mem_cache[url] = val


def _get_from_cache(url, include_old=False):
    now = datetime.utcnow()
    now = now.replace(tzinfo=timezone.utc)
    if CACHE_SYSTEM == 'redis':
        redis_db.get(url)
    else:
        if url not in mem_cache:
            return None
        if mem_cache[url]['expire_at'] >= now.timestamp() or include_old:
            return mem_cache[url]['data']
        else:
            del mem_cache[url]
            return None


def _get_error_json(path, cache_time=CACHE_EXPIRE_SECONDS):
    file_path = f'{path[1:]}.json'
    end_dt = datetime.utcnow() + timedelta(seconds=cache_time)
    end_dt = end_dt.replace(tzinfo=timezone.utc)
    start_dt = datetime.utcnow()
    start_dt = start_dt.replace(tzinfo=timezone.utc)
    page = {
        'start': start_dt,
        'end': end_dt,
        'duration': cache_time
    }
    try:
        template = err_env.get_template(file_path)
        data = json.loads(template.render(page=page))
    except Exception as e:
        data = {}
    return data

def _clear_cache(status):
    if status == 'NOT_FULL_OF_SHIT':
        if CACHE_SYSTEM == 'redis':
            redis_db.flushall()
            return True
        else:
            mem_cache.clear()
            return True
    return False


def _clear_posts(status):
    prefix = 'https://wdwnt.com/wp-json/wp/v2/posts'
    if status == 'NOT_FULL_OF_SHIT':
        if CACHE_SYSTEM == 'redis':
            for key in redis_db.scan_iter(prefix + '*'):
                redis_db.delete(key)
            return True
        else:
            to_del = set()
            for k in mem_cache.keys():
                if k.startswith(prefix):
                    to_del.add(k)
            for l in to_del:
                mem_cache.pop(l)
            return True
    return False

@app.route('/settings')
def settings_call():
    if GIT_COMMIT:
        ver = GIT_COMMIT
    else:
        ver = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'])
        ver = ver.decode().rstrip()
    # TODO - Expand with more settings like environment variables.
    return jsonify({
        'version': ver,
        'description': GIT_DESCRIPTION,
        'deployed_at': GIT_RELEASE_AT,
        'mem_cache': mem_cache
    })


@app.route('/youtube')
def youtube():
    max_results = request.args.get('maxResults', YOUTUBE_VIDS_PER_PAGE)
    page_token = request.args.get('page_token', None)

    if not (YOUTUBE_API_KEY and YOUTUBE_PLAYLIST_ID):
        return jsonify({})
    url = 'https://www.googleapis.com/youtube/v3/playlistItems?part=snippet' \
          '&maxResults={}&playlistId={}&key={}'.format(max_results,
                                                       YOUTUBE_PLAYLIST_ID,
                                                       YOUTUBE_API_KEY)
    if page_token:
        url += '&pageToken={}'.format(page_token)

    response_dict = _get_from_cache(url)
    if not response_dict:
        response = requests.get(url)
        response_dict = format_youtube(response.json())
        _store_in_cache(url, response_dict)
    return jsonify(response_dict)


@app.route('/broadcasts', strict_slashes=False)
def broadcasts():
    if not (BROADCAST_CLIENT_ID and BROADCAST_CLIENT_SECRET and BROADCAST_REFRESH_TOKEN):
        return jsonify({})
    response_dict = _get_from_cache('broadcasts')
    if not response_dict:
        yb = YoutubeBroadcasts(BROADCAST_CLIENT_ID, BROADCAST_CLIENT_SECRET, BROADCAST_REFRESH_TOKEN)
        response_dict = yb.get_broadcasts()
        old_response = _get_from_cache('broadcasts', include_old=True)
        old_response = {} if old_response is None else old_response
        all_upcoming = response_dict['upcoming'] + old_response.get('upcoming', [])
        response_dict['upcoming'] = list({v['id']: v for v in all_upcoming if v['id'] not in
                                          [x['id'] for x in response_dict['live']]}.values())
        _store_in_cache('broadcasts', response_dict, expire_seconds=BROADCAST_EXPIRE_SECONDS)
    return jsonify(response_dict)


@app.route('/broadcasts/wigs', strict_slashes=False)
def wigs_broadcasts():
    if not (BROADCAST_CLIENT_ID and BROADCAST_CLIENT_SECRET and BROADCAST_REFRESH_TOKEN):
        return jsonify({})
    response_dict = _get_from_cache('broadcasts/unlisted')
    if not response_dict:
        yb = YoutubeBroadcasts(BROADCAST_CLIENT_ID, BROADCAST_CLIENT_SECRET, BROADCAST_REFRESH_TOKEN)
        response_dict = yb.get_broadcasts(show_unlisted=True)
        old_response = _get_from_cache('broadcasts', include_old=True)
        old_response = {} if old_response is None else old_response
        all_upcoming = response_dict['upcoming'] + old_response.get('upcoming', [])
        response_dict['upcoming'] = list({v['id']: v for v in all_upcoming if v['id'] not in
                                          [x['id'] for x in response_dict['live']]}.values())
        _store_in_cache('broadcasts/unlisted', response_dict, expire_seconds=BROADCAST_EXPIRE_SECONDS)
    return jsonify(response_dict)


@app.route('/broadcasts/debug', strict_slashes=False)
def debug_broadcasts():
    if not (BROADCAST_CLIENT_ID and BROADCAST_CLIENT_SECRET and BROADCAST_REFRESH_TOKEN):
        return jsonify({})
    yb = YoutubeBroadcasts(BROADCAST_CLIENT_ID, BROADCAST_CLIENT_SECRET, BROADCAST_REFRESH_TOKEN)
    response_dict = yb.get_broadcasts(show_unlisted=True, debug=True)
    return jsonify(response_dict)


@app.route('/podcasts', strict_slashes=False)
def podcasts():
    in_per_page = request.args.get('per_page', POSTS_PER_PAGE)
    in_page = request.args.get('page', 1)
    with_content = 'nocontent' not in request.args
    with_player = 'noplayer' not in request.args
    url = 'https://podcasts.wdwnt.com/wp-json/wp/v2/posts?per_page={}&page={}&_embed'
    url = url.format(in_per_page, in_page)
    cache_url = '{}|{}|{}'.format('WithContent' if with_content else 'NoContent',
                                  'WithPlayer' if with_player else 'NoPlayer', url)
    # TODO - use cache data with content/player to populate NoContent/NoPlayer
    # print(url)
    response_dict = _get_from_cache(cache_url)
    if not response_dict:
        response = requests.get(url, headers=WP_HEADER)
        response_dict = format_wp(response.json(), with_content=with_content, with_player=with_player)
        _store_in_cache(cache_url, response_dict)
    return jsonify(response_dict)


@app.route('/podcasts/<int:post_id>')
def single_podcast(post_id):
    # Do something with page_id
    url = 'https://podcasts.wdwnt.com/wp-json/wp/v2/posts/{}?_embed'
    url = url.format(post_id)
    # print(url)
    with_player = 'noplayer' not in request.args
    cache_url = '{}|{}'.format('WithPlayer' if with_player else 'NoPlayer', url)
    response_dict = _get_from_cache(cache_url)
    if not response_dict:
        response = requests.get(url, headers=WP_HEADER)
        response_dict = format_wp_single_post(response.json(), with_player=with_player)
        _store_in_cache(cache_url, response_dict)
    return jsonify(response_dict)


@app.route('/posts', strict_slashes=False)
def posts():
    in_per_page = request.args.get('per_page', POSTS_PER_PAGE)
    in_page = request.args.get('page', 1)
    in_slug = request.args.get('slug', '')
    in_categories = request.args.get('categories', '')
    in_search = request.args.get('search', '')
    add_to_cache = True
    if in_slug:
        url = 'https://wdwnt.com/wp-json/wp/v2/posts?slug={}&_embed'
        url = url.format(in_slug)
    elif in_categories:
        url = 'https://wdwnt.com/wp-json/wp/v2/posts?categories={}&per_page={}&page={}&_embed'
        url = url.format(in_categories, in_per_page, in_page)
    elif in_search:
        url = 'https://wdwnt.com/wp-json/wp/v2/posts?search={}&per_page={}&page={}&_embed'
        url = url.format(in_search, in_per_page, in_page)
        add_to_cache = False
    else:
        url = 'https://wdwnt.com/wp-json/wp/v2/posts?per_page={}&page={}&_embed'
        url = url.format(in_per_page, in_page)
    # print(url)
    response_dict = _get_from_cache(url)
    if not response_dict:
        response = requests.get(url, headers=WP_HEADER)
        response_dict = format_wp(response.json())
        if add_to_cache:
            _store_in_cache(url, response_dict)
    return jsonify(response_dict)


@app.route('/posts/<int:post_id>')
def single_post(post_id):
    # Do something with page_id
    url = 'https://wdwnt.com/wp-json/wp/v2/posts/{}?_embed'
    url = url.format(post_id)
    # print(url)
    response_dict = _get_from_cache(url)
    if not response_dict:
        response = requests.get(url, headers=WP_HEADER)
        response_dict = format_wp_single_post(response.json())
        _store_in_cache(url, response_dict)
    return jsonify(response_dict)


@app.route('/pages', strict_slashes=False)
def pages():
    in_per_page = request.args.get('per_page', POSTS_PER_PAGE)
    in_page = request.args.get('page', 1)
    in_slug = request.args.get('slug', '')
    if in_slug:
        url = 'https://wdwnt.com/wp-json/wp/v2/pages?slug={}&_embed'
        url = url.format(in_slug)
    else:
        url = 'https://wdwnt.com/wp-json/wp/v2/pages?per_page={}&page={}&_embed'
        url = url.format(in_per_page, in_page)
    # print(url)
    response_dict = _get_from_cache(url)
    if not response_dict:
        response = requests.get(url, headers=WP_HEADER)
        response_dict = format_wp(response.json())
        _store_in_cache(url, response_dict)
    return jsonify(response_dict)


@app.route('/pages/<int:post_id>')
def single_page(post_id):
    # Do something with page_id
    url = 'https://wdwnt.com/wp-json/wp/v2/pages/{}?_embed'
    url = url.format(post_id)
    # print(url)
    response_dict = _get_from_cache(url)
    if not response_dict:
        response = requests.get(url, headers=WP_HEADER)
        response_dict = format_wp_single_post(response.json())
        _store_in_cache(url, response_dict)
    return jsonify(response_dict)


@app.route('/announcements', strict_slashes=False)
def announcements():
    # url = 'https://wdwnt.com/wp-json/wp/v2/announcements?appflag=7566,7568'
    # https://wdwnt.com/wp-json/wp/v2/appflag?include=7566,7568
    url = 'https://wdwnt.com/wp-json/wp/v2/announcements?_embed'
    response_dict = _get_from_cache(url)
    if not response_dict:
        response = requests.get(url, headers=WP_HEADER)
        response_dict = {}
        for a_id, slug in WP_APPFLAGS.items():
            response_dict[slug] = [format_wp_single_post(x, with_icon=True)
                                   for x in response.json()
                                   if x['appflag'][0] == a_id]
        _store_in_cache(url, response_dict)
    return jsonify(response_dict)


@app.route('/notifications', strict_slashes=False)
def notifications():
    in_per_page = request.args.get('per_page', POSTS_PER_PAGE)
    in_page = request.args.get('page', 1)
    url = 'https://wdwnt.com/wp-json/wp/v2/app_notification?per_page={}&page={}'
    url = url.format(in_per_page, in_page)
    response_dict = _get_from_cache(url)
    if not response_dict:
        response = requests.get(url, headers=WP_HEADER)
        response_dict = format_notifications(response.json())
        _store_in_cache(url, response_dict)
    return jsonify(response_dict)


@app.route('/radio')
def radio():
    url = 'https://wdwnt.airtime.pro/api/live-info'
    response_dict = _get_from_cache(url)
    if not response_dict:
        response = requests.get(url)
        try:
            response.raise_for_status()
            response_dict = format_airtime(response.json())
        except requests.exceptions.HTTPError:
            _store_in_cache(url, {}, expire_seconds=CACHE_EXPIRE_SECONDS)
            return jsonify({})
        if response_dict['current']['type'] == 'livestream':
            expiry = datetime.utcnow() + timedelta(seconds=CACHE_EXPIRE_SECONDS)
            expiry = expiry.replace(tzinfo=timezone.utc)
            response_dict['current']['ends'] = expiry
            response_dict['current']['metadata']['length'] = str(timedelta(seconds=CACHE_EXPIRE_SECONDS))
            _store_in_cache(url, response_dict)
        else:
            ending = parser.parse(response_dict['current']['ends'])
            ending = ending.replace(tzinfo=timezone.utc)
            # pprint(ending)
            _store_in_cache(url, response_dict, expire_time=ending)
    return jsonify(response_dict)


@app.route('/live365')
def live365():
    url = 'https://api.live365.com/station/a31769'
    response_dict = _get_from_cache(url)
    if not response_dict:
        response = requests.get(url)
        try:
            response.raise_for_status()
            response_dict = format_live365(response.json())
        except requests.exceptions.HTTPError:
            err_resp = _get_error_json(request.path)
            _store_in_cache(url, err_resp, expire_seconds=CACHE_EXPIRE_SECONDS)
            return jsonify(err_resp)
        if response_dict['live_dj_on']:
            expiry = datetime.utcnow() + timedelta(seconds=CACHE_EXPIRE_SECONDS)
            expiry = expiry.replace(tzinfo=timezone.utc)
            response_dict['current-track']['end'] = expiry
            response_dict['current-track']['duration'] = str(timedelta(seconds=CACHE_EXPIRE_SECONDS))
            _store_in_cache(url, response_dict)
        else:
            if response_dict['current-track'].get('end') is None:
                ending = datetime.utcnow() + timedelta(seconds=CACHE_EXPIRE_SECONDS)
                ending = ending.replace(tzinfo=timezone.utc)
            else:
                ending = parser.parse(response_dict['current-track']['end'])
            _store_in_cache(url, response_dict, expire_time=ending)
    return jsonify(response_dict)


@app.route('/clear', methods=['POST'])
def clear_cache():
    data = request.json
    if data is not None:
        status = data.get('status')
    else:
        status = ''
    resp = _clear_cache(status)
    return ('', 204) if resp else (jsonify({'status': 'Invalid status'}), 401)


@app.route('/refresh_posts', methods=['POST'])
def clear_posts():
    data = request.json
    if data is not None:
        status = data.get('status')
    else:
        status = ''
    resp = _clear_posts(status)
    return ('', 204) if resp else (jsonify({'status': 'Invalid status'}), 401)


@app.route('/unlisted_videos')
def unlisted_videos():
    in_delta_minutes = int(request.args.get('delta_minutes', UNLISTED_VIDEO_EXPIRE_SECONDS/60))
    if not (BROADCAST_CLIENT_ID and BROADCAST_CLIENT_SECRET and BROADCAST_REFRESH_TOKEN):
        return jsonify({})
    response_list = _get_from_cache('unlisted_videos')
    if not response_list:
        yb = YoutubeBroadcasts(BROADCAST_CLIENT_ID, BROADCAST_CLIENT_SECRET, BROADCAST_REFRESH_TOKEN)
        response_list = yb.get_unlisted_videos(in_delta_minutes)
        _store_in_cache('unlisted_videos', response_list, expire_seconds=UNLISTED_VIDEO_EXPIRE_SECONDS)
        sm = SlackMessenger()
        for video in response_list:
            slack_msg = 'A new video has been uploaded to the WDWNT YouTube Channel and may need a cover image.' \
                        ' {} https://www.youtube.com/watch?v={}'
            msg = slack_msg.format(video['title'], video['id'])
            sm.send(msg, 'youtube', 'YouTube Unlisted FastPass ZapBot', ':youtube:')
    return jsonify(response_list)


@app.route('/')
def root_page():
    return app.send_static_file('index.html')


if __name__ == '__main__':
    app.run(debug=True, port=SERVER_PORT)
