#!/bin/bash
export DOCKER_BUILDKIT=1

set -e

DIR="$( cd "$( dirname "$0" )" && pwd )"
DOCKERFILE="$DIR/Dockerfile"
BUILD_DATE="$(date -u +'%Y-%m-%d')"
GIT_REPOSITORY=https://github.com/lavanet/lava.git

NODE_TYPES=("RPC Node" "Validator Node")

PS3="Select node type: "
select node_type in "${NODE_TYPES[@]}"
do
    case $node_type in
        "RPC Node")
            LAVA_BINARY="lava-protocol"; break
            ;;
        "Validator Node")
            LAVA_BINARY="lavad"; break
            ;;
    esac
done

read -p "Enter image name: " -r IMAGE_NAME
read -p "Enter release tag: " -r IMAGE_TAG
read -p "Do you want to send the image to DockerHub [yes/no]: " -r PUSH_FLAG

while [[ "$PUSH_FLAG" != "yes" && "$PUSH_FLAG" != "no" ]]
do
    read -r -p "Please answer yes/no: " PUSH_FLAG
done

if [[ "$PUSH_FLAG" == "yes" ]]
then
    read -r -p "Enter username: " DOCKERHUB_USERNAME
    read -r -p "Enter password: " DOCKERHUB_PASSWORD
    IMAGE=$DOCKERHUB_USERNAME/$IMAGE_NAME:$IMAGE_TAG
else
    IMAGE=$IMAGE_NAME:$IMAGE_TAG
fi

echo -e "\nBuilding node"
echo -e "Build date: \t$BUILD_DATE"
echo -e "Dockerfile: \t$DOCKERFILE"
echo -e "Docker context: $DIR"
echo -e "Docker Image: \t$IMAGE"
echo -e "Node type: \t$node_type"
echo -e "Version: \t$IMAGE_TAG\n"

echo -e "IMAGE=${IMAGE}\nCOMPOSE_PROJECT_NAME=lava" > .env m

docker build -f "$DOCKERFILE" "$DIR" \
    --build-arg IMAGE_TAG="$IMAGE_TAG" \
    --build-arg GIT_REPOSITORY="$GIT_REPOSITORY" \
    --build-arg LAVA_BINARY="$LAVA_BINARY" \
    --build-arg BUILD_DATE="$BUILD_DATE" \
    --tag $IMAGE

if [[ "$PUSH_FLAG" == "yes" ]]
then
    echo -e "\nSending docker image \"$IMAGE\" to DockerHub\n"
    docker login -u $DOCKERHUB_USERNAME -p $DOCKERHUB_PASSWORD 2>/dev/null
    docker push $IMAGE
fi

echo -e "\nThe build is complete\n"