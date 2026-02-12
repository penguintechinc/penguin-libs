#!/bin/bash

# === Health Check Step ===
# Verify build validator job succeeded and extract logs

set -e

PROJECT_NAME="penguin-libs"
NAMESPACE="penguin-libs-beta"

echo "Performing health checks for namespace: $NAMESPACE"

# Check if job exists and succeeded
JOB_NAME="$PROJECT_NAME-build-test"
JOB_SUCCEEDED=$(kubectl get job "$JOB_NAME" -n "$NAMESPACE" -o jsonpath='{.status.succeeded}' 2>/dev/null || echo "0")

if [ "$JOB_SUCCEEDED" != "1" ]; then
    echo "ERROR: Build validator job did not succeed"
    echo ""
    echo "Job status:"
    kubectl get job "$JOB_NAME" -n "$NAMESPACE"
    echo ""
    echo "Pod logs:"
    kubectl logs -n "$NAMESPACE" -l job-name="$JOB_NAME" --all-containers=true --tail=100
    exit 1
fi

echo "Build validator job health check: PASSED"
echo ""
echo "Job completion details:"
kubectl get job "$JOB_NAME" -n "$NAMESPACE" -o wide

echo ""
echo "Pod status:"
kubectl get pods -n "$NAMESPACE" -l job-name="$JOB_NAME"

echo ""
echo "Build validator output:"
kubectl logs -n "$NAMESPACE" -l job-name="$JOB_NAME" --all-containers=true

echo ""
echo "Health checks completed successfully"
