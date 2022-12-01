#!/bin/sh
# USAGE: ./build.sh <tag>
export DOCKER_BUILDKIT=1

set -e

if [ ! $1 ]
then 
    echo "Error. Tag not specified"
    exit 1
fi

IMAGE_TAG="$1"
GIT_REPOSITORY=https://github.com/solarlabsteam/cosmos-exporter.git
DIR="$( cd "$( dirname "$0" )" && pwd )"
DOCKERFILE="$DIR/Dockerfile"
BUILD_DATE="$(date -u +'%Y-%m-%d')"

echo
echo "Building cosmos-exporter docker image"
echo "Dockerfile: \t$DOCKERFILE"
echo "Docker context: $DIR"
echo "Build date: \t$BUILD_DATE"
echo "Version: \t$IMAGE_TAG"
echo

if [ "$(uname)" == "Darwin" ]
then
    sed -i "" "s/^TAG=.*$/TAG=${IMAGE_TAG}/" "$DIR/.env"
else
    sed -i "s/^TAG=.*$/TAG=${IMAGE_TAG}/" "$DIR/.env"
fi

docker build -f "$DOCKERFILE" "$DIR" \
     --build-arg IMAGE_TAG="$IMAGE_TAG" \
     --build-arg GIT_REPOSITORY="$GIT_REPOSITORY" \
     --build-arg BUILD_DATE="$BUILD_DATE" \
     --tag svetekllc/cosmos-exporter:$IMAGE_TAG

docker push svetekllc/cosmos-exporter:$IMAGE_TAG