#!/bin/bash

# === Wait for Readiness Step ===
# Monitor job completion for build validator

set -e

PROJECT_NAME="penguin-libs"
NAMESPACE="penguin-libs-beta"
MAX_WAIT=300  # 5 minutes
INTERVAL=5    # Check every 5 seconds
ELAPSED=0

echo "Waiting for build validator job to complete in namespace: $NAMESPACE"

while [ $ELAPSED -lt $MAX_WAIT ]; do
    # Check job status
    JOB_NAME="$PROJECT_NAME-build-test"
    JOB_STATUS=$(kubectl get job "$JOB_NAME" -n "$NAMESPACE" -o jsonpath='{.status.succeeded}' 2>/dev/null || echo "0")

    if [ "$JOB_STATUS" = "1" ]; then
        echo "Build validator job completed successfully"
        exit 0
    fi

    # Check for failures
    JOB_FAILED=$(kubectl get job "$JOB_NAME" -n "$NAMESPACE" -o jsonpath='{.status.failed}' 2>/dev/null || echo "0")
    if [ "$JOB_FAILED" -gt "0" ]; then
        echo "Build validator job failed"
        kubectl logs -n "$NAMESPACE" -l job-name="$JOB_NAME" --all-containers=true --tail=50
        exit 1
    fi

    echo "Job still running... ($ELAPSED/$MAX_WAIT seconds)"
    sleep $INTERVAL
    ELAPSED=$((ELAPSED + INTERVAL))
done

echo "Timeout waiting for job to complete"
exit 1
