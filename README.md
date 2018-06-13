# fastpass
Server caching for API calls

## To run in Docker
* Build the container: `docker build -t fastpass:latest .`

* Run the container: ` docker run -p 5000:5000 -e [environment_variable]='[value]' fastpass:latest`

## Environment Variables

* `FASTPASS_CACHE_EXPIRE_SECONDS` - General time in seconds for cache expiration. Default is `180`.
* `FASTPASS_HOST_PORT` - HTTP Port on which the service runs. Default is `5000`.
* Posts
    * `FASTPASS_POSTS_PER_PAGE` - Number of posts returned per page. Default is `30`.
* YouTube
    * `FASTPASS_YOUTUBE_VIDS_PER_PAGE` - Number of video entities to pull per page. Default is `30`.
    * `FASTPASS_YOUTUBE_API_KEY` - YouTube issued API key. Default is `None`.
    * `FASTPASS_YOUTUBE_PLAYLIST_ID` - YouTube ID of playlist to pull entities from. Default is `None`.
    * `FASTPASS_YOUTUBE_EXPIRE_SECONDS`
* Redis
    * `FASTPASS_REDIS_HOST` - Redis host location. Default is `127.0.0.1`.
    * `FASTPASS_REDIS_PORT` - Redis port. Default is `36379`.
    * `FASTPASS_REDIS_PASSWORD` - Redis password. Default is `''`.
    * `FASTPASS_REDIS_USE_SSL` - Boolean to determine whether or not to use SSL in Redis connection. Default is `False`.
