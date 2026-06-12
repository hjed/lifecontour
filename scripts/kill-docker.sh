#!/bin/bash
NUMBER=$1
docker kill pms_test_${NUMBER}-backend pms_test_${NUMBER}-oauth-login-consent pms_test_${NUMBER}-google-worker pms_test_${NUMBER}-postgres pms_test_${NUMBER}-redis pms_test_${NUMBER}-meilisearch pms_test_${NUMBER}-oauth pms_test_${NUMBER}-strava-worker pms_test_${NUMBER}-snipeit-worker pms_test_${NUMBER}-immich-worker
