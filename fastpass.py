# import time

import os
from datetime import datetime, timedelta, timezone
import html

import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

CACHE_EXPIRE_SECONDS = os.getenv('FASTPASS_CACHE_EXPIRE_SECONDS', 180)
SERVER_PORT = os.getenv('FASTPASS_HOST_PORT', 5000)
POSTS_PER_PAGE = os.getenv('FASTPASS_POSTS_PER_PAGE', 30)
YOUTUBE_VIDS_PER_PAGE = os.getenv('FASTPASS_YOUTUBE_VIDS_PER_PAGE', 30)
YOUTUBE_API_KEY = os.getenv('FASTPASS_YOUTUBE_API_KEY', None)
YOUTUBE_PLAYLIST_ID = os.getenv('FASTPASS_YOUTUBE_PLAYLIST_ID', None)
YOUTUBE_EXPIRE_SECONDS = os.getenv('FASTPASS_YOUTUBE_EXPIRE_SECONDS', CACHE_EXPIRE_SECONDS)
REDIS_HOST = os.getenv('FASTPASS_REDIS_HOST', '127.0.0.1')
REDIS_PORT = os.getenv('FASTPASS_REDIS_PORT', 36379)
REDIS_PASSWORD = os.getenv('FASTPASS_REDIS_PASSWORD', '')
REDIS_USE_SSL = os.getenv('FASTPASS_REDIS_USE_SSL', False)

app = Flask(__name__)
CORS(app)

mem_cache = {}


def format_airtime(in_data):
    result = {'current': {}, 'currentShow': [], 'next': {}}
    result['current']['ends'] = in_data.get('current', {}).get('ends')
    for song in ('current', 'next'):
        md_block = {}
        for field in ('track_title', 'artist_name', 'length'):
            md_block[field] = in_data.get(song, {})\
                .get('metadata', {})\
                .get(field)
        result[song]['metadata'] = md_block
    if len(in_data.get('currentShow', [])):
        show_data = in_data['currentShow'][0]
        show_block = {}
        for field in ('name', 'image_path'):
            show_block[field] = show_data.get(field)
        result['currentShow'].append(show_block)

    return result


def format_wp(in_data, with_content=False):
    result = []
    for post in in_data:
        obj = dict(author={})
        obj['short_URL'] = post.get('guid', {}).get('rendered')
        obj['title'] = html.unescape(post.get('title', {}).get('rendered', ''))
        obj['date'] = post.get('date_gmt')
        authors = post.get('_embedded', {}).get('author', [])
        obj['author']['name'] = ','.join([x.get('name') for x in authors])
        # TODO - Featured Image
        media = post.get('_embedded', {}).get('wp:featuredmedia', [])
        if media:
            obj['featured_image'] = media[0].get('source_url')
        else:
            obj['featured_image'] = ''

        if with_content:
            obj['content'] = post.get('content', {}).get('rendered', '')
        result.append(obj)
    return result


def format_youtube(in_data):
    result = {'items': []}
    result['nextPageToken'] = in_data.get('nextPageToken')
    result['prevPageToken'] = in_data.get('prevPageToken')
    for x in in_data.get('items', []):
        obj = dict(snippet=dict(resourceId={}, thumbnails={'default': {}}))
        obj['snippet']['resourceId']['videoId'] = \
            x.get('snippet', {}).get('resourceId', {}).get('videoId')
        obj['snippet']['thumbnails']['default']['url'] = \
            x.get('snippet', {}).get('thumbnails', {}).get('default', {}).get('url')
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

    val = {
        'data': data,
        'expire_at': expiry.timestamp(),
    }
    mem_cache[url] = val


def _get_from_cache(url):
    now = datetime.utcnow()
    now = now.replace(tzinfo=timezone.utc)
    if url not in mem_cache:
        return None
    if mem_cache[url]['expire_at'] >= now.timestamp():
        return mem_cache[url]['data']
    else:
        del mem_cache[url]
        return None


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


@app.route('/podcasts')
def podcasts():
    per_page = request.args.get('per_page', POSTS_PER_PAGE)
    page = request.args.get('page', 1)
    url = 'https://podcasts.wdwnt.com/wp-json/wp/v2/posts?' \
          'per_page={}&page={}&_embed'
    url = url.format(per_page, page)
    # print(url)
    response_dict = _get_from_cache(url)
    if not response_dict:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/50.0.2661.102 Safari/537.36'}
        response = requests.get(url, headers=headers)
        response_dict = format_wp(response.json(), with_content=True)
        _store_in_cache(url, response_dict)
    return jsonify(response_dict)


@app.route('/posts')
def posts():
    per_page = request.args.get('per_page', POSTS_PER_PAGE)
    page = request.args.get('page', 1)
    url = 'https://wdwnt.com/wp-json/wp/v2/posts?per_page={}&page={}&_embed'
    url = url.format(per_page, page)
    # print(url)
    response_dict = _get_from_cache(url)
    if not response_dict:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/50.0.2661.102 Safari/537.36'}
        response = requests.get(url, headers=headers)
        response_dict = format_wp(response.json())
        _store_in_cache(url, response_dict)
    return jsonify(response_dict)


@app.route('/radio')
def radio():
    url = 'https://wdwnt.airtime.pro/api/live-info'
    date_form = '%Y-%m-%d %H:%M:%S'
    response_dict = _get_from_cache(url)
    if not response_dict:
        response = requests.get(url)
        response_dict = format_airtime(response.json())
        ending = datetime.strptime(response_dict['current']['ends'], date_form)
        ending = ending.replace(tzinfo=timezone.utc)
        # pprint(ending)
        _store_in_cache(url, response_dict, expire_time=ending)
    return jsonify(response_dict)


if __name__ == '__main__':
    app.run(debug=True, port=SERVER_PORT)
