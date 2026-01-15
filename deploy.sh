#!/bin/bash

# Get MongoDB connection and Container Registry
echo "Lies .env ein..."
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
echo "Checke Verbindung zu AWS..."
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
if [ -z "$AWS_ACCOUNT_ID" ]; then
  echo "AWS CLI nicht verbunden. Bitte ~/.aws/credentials anpassen oder 'aws sso login' ausführen"
  exit 3
fi

test -n "$STACK_NAME" || STACK_NAME="xkcd-bot-stack"

echo "Setze Docker Namen und Pfade..."
test -n "$ECR_REPO" || ECR_REPO="xkcd-backend"
test -n "$IMAGE_TAG" || IMAGE_TAG="latest"
DOCKER_IMAGE="${ECR_REPO}:${IMAGE_TAG}"
test -n "$AWS_REGION" || AWS_REGION=$(aws configure get region)
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
ECR_IMAGE="${ECR_REGISTRY}/${DOCKER_IMAGE}"

# SSH key pair for backend instance
echo "Checke SSH Key..."
test -n "$SSH_KEY_FILE" || SSH_KEY_FILE='.env.d/id_rsa_xkcdbot'
if [ ! -f $SSH_KEY_FILE ]; then
  echo "Erstelle SSH Key in $SSH_KEY_FILE"
  ssh-keygen -t rsa -b 4096 -f "$SSH_KEY_FILE" -C "xkcdBot-deploy" -N ""
fi

# Deploy CloudFormation stack
echo "Deploye CloudFormation Stack..."
aws cloudformation deploy \
  --template-file template.yaml \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION" \
  --parameter-overrides SshPublicKey="$(cat ${SSH_KEY_FILE}.pub)" \
    MongoUri="$MONGO_URI" \
    MongoDb="$MONGO_DB" \
    MongoCollection="$MONGO_COLLECTION" \
    EcrRepo="$ECR_REPO" \
  --capabilities CAPABILITY_NAMED_IAM

if [ $? -ne 0 ]; then
  echo "CloudFormation Deployment fehlgeschlagen!"
  exit 4
fi

# Get backend EC2 instance public IP
EC2_IP=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='BackendPublicIp'].OutputValue" \
  --output text)


# Build Docker Image and Push to repo
echo "Baue Docker Image und lade zu ECR..."
aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin "$ECR_REGISTRY"
docker build -t "$DOCKER_IMAGE" .
docker tag "$DOCKER_IMAGE" "$ECR_IMAGE"
docker push "$ECR_IMAGE"

# Run Container on EC2 instance:
echo "Verbinde mit EC2 Instanz und Starte Container..."
scp -o StrictHostKeyChecking=no -i "$SSH_KEY_FILE" ".env" ec2-user@"$EC2_IP":~/.env
ssh -o StrictHostKeyChecking=no -i "$SSH_KEY_FILE" ec2-user@"$EC2_IP" << EOF
  chmod 600 ~/.env
  source ~/.env
  aws ecr get-login-password --region "$AWS_REGION" | \\
  docker login --username AWS --password-stdin "$ECR_REGISTRY"
  docker run -d \\
    --name xkcd-backend \\
    --restart always \\
    -p 8000:8000 \\
    --env-file ~/.env \\
    "$ECR_IMAGE"
EOF

BUCKET=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" \
  --output text)
aws s3 sync frontend/ s3://${BUCKET}/ --delete

echo "Backend API"
echo "http://${EC2_IP}:8000"

echo "Frontend (S3):"
echo "http://${BUCKET}.s3-website.${AWS_REGION}.amazonaws.com"

echo "CloudFront URL (HTTPS):"
aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='CloudFrontUrl'].OutputValue" \
  --output text
