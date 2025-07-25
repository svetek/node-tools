#!/bin/bash
export DOCKER_BUILDKIT=1

set -e

BIN="lotus"
BUILD_DATE="$(date -u +'%Y-%m-%d')"
DIR="$( cd "$( dirname "$0" )" && pwd )"
DOCKERFILE="$DIR/Dockerfile"
GIT_REPOSITORY=https://github.com/filecoin-project/lotus

read -p "Enter image name: " -r IMAGE_NAME
read -p "Enter release tag: " -r IMAGE_TAG

echo "Do you want to send the image to DockerHub?"
PS3="Send the image to DockerHub: "
select answer in "yes" "no"
do
    case $answer in
        "yes")
            PUSH_FLAG="yes"; break
            ;;
        "no")
            PUSH_FLAG="no"; break
            ;;
    esac
done

if [[ "$PUSH_FLAG" == "yes" ]]
then
    read -r -p "Enter username: " DOCKERHUB_USERNAME
    read -r -p "Enter password: " DOCKERHUB_PASSWORD
    IMAGE=$DOCKERHUB_USERNAME/$IMAGE_NAME:$IMAGE_TAG
else
    IMAGE=$IMAGE_NAME:$IMAGE_TAG
fi

echo -e "\n\e[32m### The build information ###\e[0m"
echo -e "Build date: \t$BUILD_DATE"
echo -e "Docker context: $DIR"
echo -e "Dockerfile: \t$DOCKERFILE"
echo -e "Docker Image: \t$IMAGE"
echo -e "Version: \t$IMAGE_TAG\n"

docker build -f "$DOCKERFILE" "$DIR" \
     --build-arg IMAGE_TAG="$IMAGE_TAG" \
     --build-arg GIT_REPOSITORY="$GIT_REPOSITORY" \
     --build-arg BIN="$BIN" \
     --tag $IMAGE

if [[ "$PUSH_FLAG" == "yes" ]]
then
    echo -e "\nSending docker image \"$IMAGE\" to DockerHub\n"
    docker login -u $DOCKERHUB_USERNAME -p $DOCKERHUB_PASSWORD 2>/dev/null
    docker push $IMAGE
fi

echo -e "\n\e[32mThe build is complete! \n\e[0m"