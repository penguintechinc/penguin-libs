#!/bin/bash

# === Wait for Readiness Step ===
# Trigger and monitor Helm test job for build validator

set -e

PROJECT_NAME="penguin-libs"
NAMESPACE="penguin-libs-beta"
MAX_WAIT=300  # 5 minutes
INTERVAL=5    # Check every 5 seconds
ELAPSED=0

echo "Running Helm test to trigger build validator job"
helm test "$PROJECT_NAME" --namespace "$NAMESPACE" --timeout 5m &
HELM_PID=$!

JOB_NAME="$PROJECT_NAME-build-test"
echo "Waiting for build validator job to complete in namespace: $NAMESPACE"

while [ $ELAPSED -lt $MAX_WAIT ]; do
    # Check if helm test already exited
    if ! kill -0 $HELM_PID 2>/dev/null; then
        wait $HELM_PID
        HELM_EXIT=$?
        if [ $HELM_EXIT -eq 0 ]; then
            echo "Build validator job completed successfully"
            exit 0
        else
            echo "Build validator job failed (helm test exit code: $HELM_EXIT)"
            kubectl logs -n "$NAMESPACE" -l job-name="$JOB_NAME" --all-containers=true --tail=50 2>/dev/null || true
            exit 1
        fi
    fi

    echo "Job still running... ($ELAPSED/$MAX_WAIT seconds)"
    sleep $INTERVAL
    ELAPSED=$((ELAPSED + INTERVAL))
done

echo "Timeout waiting for job to complete"
kill $HELM_PID 2>/dev/null || true
kubectl logs -n "$NAMESPACE" -l job-name="$JOB_NAME" --all-containers=true --tail=50 2>/dev/null || true
exit 1
