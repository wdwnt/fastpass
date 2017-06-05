# import time
import os

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
redis_conn = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD)

requests_cache.install_cache('fastpass_cache', backend='redis',
                             expire_after=CACHE_EXPIRE_SECONDS, connection=redis_conn)


@app.route('/posts/<int:page>')
@app.route('/posts', defaults={'page': 1})
def posts(page):
    url = 'http://wdwnt.com/wp-json/wp/v2/posts?_embed&per_page={}&page={}'.format(POSTS_PER_PAGE, page)
    response = requests.get(url)
    response_dict = response.json()
    # Uncomment for debugging
    # now = time.ctime(int(time.time()))
    # print("Time: {0} / Used Cache: {1}".format(now, response.from_cache))
    return jsonify(response_dict)


if __name__ == '__main__':
    app.run(debug=True, port=SERVER_PORT)
