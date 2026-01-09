#!/bin/bash

# SSH key pair for backend instance
ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa_backend-xkcdbot -C "xkcdBot-deploy"

# Deploy CloudFormation stack
aws cloudformation deploy \
  --template-file template.yaml \
  --stack-name xkcd-bot-stack \
  --parameter-overrides SshPublicKey="$(cat ~/.ssh/id_rsa_backend-xkcdbot.pub)" \
  --capabilities CAPABILITY_NAMED_IAM

# Get backend EC2 instance public IP
EC2IP=$(aws cloudformation describe-stacks \
  --stack-name xkcd-bot-stack \
  --query "Stacks[0].Outputs[?OutputKey=='BackendPublicIp'].OutputValue" \
  --output text)