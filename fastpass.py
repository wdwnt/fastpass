# import time

import os
from datetime import datetime, timedelta, timezone
import html

import requests
from flask import Flask, jsonify, request

SERVER_PORT = os.getenv('FASTPASS_HOST_PORT', 80)
POSTS_PER_PAGE = os.getenv('FASTPASS_POSTS_PER_PAGE', 30)
REDIS_HOST = os.getenv('FASTPASS_REDIS_HOST', '127.0.0.1')
REDIS_PORT = os.getenv('FASTPASS_REDIS_PORT', 36379)
REDIS_PASSWORD = os.getenv('FASTPASS_REDIS_PASSWORD', '')
CACHE_EXPIRE_SECONDS = os.getenv('FASTPASS_CACHE_EXPIRE_SECONDS', 180)

app = Flask(__name__)

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

def format_wp(in_data):
    result = []
    for post in in_data:
        obj = {}
        obj['short_URL'] = post.get('guid',{}).get('rendered')
        obj['title'] = html.unescape(post.get('title',{}).get('rendered', ''))
        authors = post.get('_embedded', {}).get('author', [])
        obj['author'] = {}
        obj['author']['name'] = ','.join([x.get('name') for x in authors])
        # TODO - Featured Image
        media = post.get('_embedded', {}).get('wp:featuredmedia', [])
        if media:
            obj['featured_image'] = media[0].get('source_url')
        else:
            obj['featured_image'] = ''
        result.append(obj)
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


@app.route('/posts')
def posts():
    per_page = request.args.get('per_page', POSTS_PER_PAGE)
    page = request.args.get('page', 1)
    url = 'http://wdwnt.com/wp-json/wp/v2/posts?per_page={}&page={}&_embed'
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
