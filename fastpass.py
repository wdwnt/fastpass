# import time
import os
from datetime import datetime, timedelta
import time
import requests
import requests_cache
import redis
from flask import Flask, jsonify

SERVER_PORT = os.getenv('FASTPASS_HOST_PORT', 80)
POSTS_PER_PAGE = os.getenv('FASTPASS_POSTS_PER_PAGE', 30)
REDIS_HOST = os.getenv('FASTPASS_REDIS_HOST', '127.0.0.1')
REDIS_PORT = os.getenv('FASTPASS_REDIS_PORT', 36379)
REDIS_PASSWORD = os.getenv('FASTPASS_REDIS_PASSWORD', '')
CACHE_EXPIRE_SECONDS = os.getenv('FASTPASS_CACHE_EXPIRE_SECONDS', 180)

app = Flask(__name__)
# redis_conn = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD)
#
# requests_cache.install_cache('fastpass_cache', backend='redis',
#                              expire_after=CACHE_EXPIRE_SECONDS, connection=redis_conn)
mem_cache = {}

def _store_in_cache(url, data, expire_time=None, expire_seconds=CACHE_EXPIRE_SECONDS):
    if not expire_time:
        expire_time = datetime.now() + timedelta(seconds=expire_seconds)
    val = {
        'data': data,
        'expire_at': expire_time.timestamp(),
    }
    mem_cache[url] = val

def _get_from_cache(url):
    if url not in mem_cache:
        return None
    if mem_cache[url]['expire_at'] >= datetime.now().timestamp():
        return mem_cache[url]['data']
    else:
        del mem_cache[url]
        return None


@app.route('/posts/<int:page>')
@app.route('/posts', defaults={'page': 1})
def posts(page):
    url = 'http://wdwnt.com/wp-json/wp/v2/posts?per_page={}&page={}'.format(POSTS_PER_PAGE, page)
    print(url)
    response_dict =  _get_from_cache(url)
    if not response_dict:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/50.0.2661.102 Safari/537.36'}
        response = requests.get(url, headers=headers)
        response_dict = response.json()
        _store_in_cache(url, response_dict)

    return jsonify(response_dict)


if __name__ == '__main__':
    app.run(debug=True, port=SERVER_PORT)
