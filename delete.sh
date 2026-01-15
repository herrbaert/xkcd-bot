BUCKET=$(aws cloudformation describe-stacks \
  --stack-name xkcd-bot-stack \
  --region "$AWS_REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" \
  --output text)
aws s3 rm s3://$BUCKET --recursive
aws cloudformation delete-stack --stack-name xkcd-bot-stack