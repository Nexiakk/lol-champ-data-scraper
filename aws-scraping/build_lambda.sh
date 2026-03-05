#!/bin/bash

# Build AWS Lambda deployment package

echo "Installing dependencies..."
pip install -r requirements.txt --target ./package

echo "Copying source code..."
cp -r scraper ./package/
cp lambda_function.py ./package/

echo "Creating deployment package..."
cd package
zip -r ../lambda-deployment.zip .
cd ..

echo "Cleaning up..."
rm -rf package

echo "Deployment package created: lambda-deployment.zip"