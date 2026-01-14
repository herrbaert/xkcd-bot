#!/bin/bash

# Get MongoDB connection and Container Registry
if [ -f .env ]; then
  source .env
else
  echo ".env nicht gefunden!"
  exit 1
fi

if [ -z "$MONGO_URI" ] || [ -z "$MONGO_DB" ] || [ -z "$MONGO_COLLECTION" ]; then
  echo "MongoDB Daten fehlen in .env (MONGO_URI, MONGO_DB, MONGO_COLLECTION)"
  exit 2
fi

# Get AWS and Docker Variables
AWS_ACCOUT_ID=$(aws sts get-caller-identity --query Account --output text)
if [ -z "$AWS_ACCOUT_ID" ]; then
  echo "AWS CLI nicht verbunden. Bitte ~/.aws/credentials anpassen oder 'aws sso login' ausführen"
  exit 3
fi

test -n "$DOCKER_REGISTRY" || DOCKER_REGISTRY="xkcd-backend"
test -n "$AWS_REGION" || AWS_REGION=$(aws configure get region)
ECR_URL="${AWS_ACCOUT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
DOCKER_IMAGE="${ECR_URL}/${DOCKER_REGISTRY}:latest"

# Build Docker Image and Push to repo

aws ecr create-repository \
  --repository-name "$DOCKER_REGISTRY" \
  --region "$AWS_REGION"
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_URL"
docker build -t xkcd-backend:latest
docker tag xkcd-backend:latest "$DOCKER_IMAGE"
docker push "$DOCKER_IMAGE"


# SSH key pair for backend instance
test -n "$SSH_KEY_FILE" || SSH_KEY_FILE='~/.ssh/id_rsa_backend-xkcdbot'
if [ ! -f $SSH_KEY_FILE ]; then
  ssh-keygen -t rsa -b 4096 -f "$SSH_KEY_FILE" -C "xkcdBot-deploy" -N ""
fi

# Deploy CloudFormation stack
aws cloudformation deploy \
  --template-file template.yaml \
  --stack-name xkcd-bot-stack \
  --parameter-overrides SshPublicKey="$(cat ${SSH_KEY_FILE}.pub)" \
    MongoUri="$MONGO_URI" \
    MongoDb="$MONGO_DB" \
    MongoCollection="$MONGO_COLLECTION" \
    DockerImage="$DOCKER_IMAGE" \
  --capabilities CAPABILITY_NAMED_IAM

# Get backend EC2 instance public IP
EC2_IP=$(aws cloudformation describe-stacks \
  --stack-name xkcd-bot-stack \
  --query "Stacks[0].Outputs[?OutputKey=='BackendPublicIp'].OutputValue" \
  --output text)

# if we want to run the container later:
# ssh ec2-user@$EC2_IP -i "$SSH_KEY_FILE" docker run ...

BUCKET=$(aws cloudformation describe-stacks \
  --stack-name xkcd-bot-stack \
  --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" \
  --output text)
aws s3 sync frontend/ s3://${BUCKET}/ --delete

echo "Your Website:"
echo "http://${BUCKET}.s3-website.${AWS_REGION}.amazonaws.com
