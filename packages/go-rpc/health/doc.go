// Copyright 2026 Penguin Tech Inc
// SPDX-License-Identifier: Apache-2.0

// Package health implements prpc.health.v1.HealthService (Check and the
// streaming Watch) plus a plain GET /healthz endpoint, per spec/SPEC.md §8.
// A Checker tracks per-service serving status in memory, keyed by service
// name with the empty string standing in for whole-process health, and
// notifies Watch subscribers of status changes over buffered channels.
package health
