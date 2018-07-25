#!/bin/bash
docker build -t wdwnt/fastpass:latest .
echo "$DOCKER_PASSWORD" | docker login -u "$DOCKER_USERNAME" --password-stdin
docker push wdwnt/fastpass
