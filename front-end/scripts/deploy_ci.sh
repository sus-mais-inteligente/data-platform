#!/usr/bin/env bash
#
# Non-interactive redeploy of the SUS+ Inteligente frontend to its OCI
# Container Instance. Meant to run from CI (see
# .github/workflows/deploy-frontend.yml) but works from a local shell too,
# given the same env vars.
#
# OCI Container Instances have no in-place "update image" operation (`oci
# container-instances container-instance update --help` only touches
# display-name/tags) — the only way to roll out a new image is delete the
# running instance and create a new one, then reattach the reserved public
# IP to the new instance's VNIC. This mirrors that exact sequence, run by
# hand throughout this project's development.
#
# Required env vars:
#   OCI_COMPARTMENT_ID        tenancy/compartment OCID
#   OCI_AVAILABILITY_DOMAIN   e.g. "wxVx:SA-SAOPAULO-1-AD-1"
#   OCI_SUBNET_ID             subnet OCID for the container instance's VNIC
#   OCI_RESERVED_PUBLIC_IP_ID OCID of the reserved public IP to reattach
#   OCI_IMAGE_URL             full image ref, e.g. gru.ocir.io/ns/repo:tag
#   OCIR_USERNAME             OCIR pull-secret username (tenancy-namespace/username)
#   OCIR_AUTH_TOKEN           OCIR pull-secret auth token
#   ORACLE_USER, ORACLE_PASSWORD, ORACLE_WALLET_PASSWORD, ORACLE_DSN,
#   ORACLE_WALLET_ZIP_B64     forwarded into the container as env vars
#
# Optional:
#   OCI_DISPLAY_NAME (default sus-mais-inteligente-frontend)
#   OCI_SHAPE (default CI.Standard.E4.Flex)
#   OCI_OCPUS (default 1.0), OCI_MEMORY_GBS (default 6.0)

set -euo pipefail

DISPLAY_NAME="${OCI_DISPLAY_NAME:-sus-mais-inteligente-frontend}"
SHAPE="${OCI_SHAPE:-CI.Standard.E4.Flex}"
OCPUS="${OCI_OCPUS:-1.0}"
MEMORY_GBS="${OCI_MEMORY_GBS:-6.0}"

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

echo "==> Building container-instance payloads"
OCI_DISPLAY_NAME="$DISPLAY_NAME" python3 - "$WORKDIR" <<'PYEOF'
import base64
import json
import os
import sys

workdir = sys.argv[1]

vnics = [{"subnetId": os.environ["OCI_SUBNET_ID"], "isPublicIpAssigned": True}]
with open(f"{workdir}/vnics.json", "w") as f:
    json.dump(vnics, f)

containers = [
    {
        "displayName": os.environ["OCI_DISPLAY_NAME"],
        "imageUrl": os.environ["OCI_IMAGE_URL"],
        "environmentVariables": {
            "ORACLE_USER": os.environ["ORACLE_USER"],
            "ORACLE_PASSWORD": os.environ["ORACLE_PASSWORD"],
            "ORACLE_WALLET_PASSWORD": os.environ["ORACLE_WALLET_PASSWORD"],
            "ORACLE_DSN": os.environ["ORACLE_DSN"],
            "ORACLE_WALLET_ZIP_B64": os.environ["ORACLE_WALLET_ZIP_B64"],
        },
    }
]
with open(f"{workdir}/containers.json", "w") as f:
    json.dump(containers, f)

pull_secret = [
    {
        "secretType": "BASIC",
        "registryEndpoint": "gru.ocir.io",
        "username": base64.b64encode(os.environ["OCIR_USERNAME"].encode()).decode(),
        "password": base64.b64encode(os.environ["OCIR_AUTH_TOKEN"].encode()).decode(),
    }
]
with open(f"{workdir}/pull_secret.json", "w") as f:
    json.dump(pull_secret, f)
PYEOF

echo "==> Looking up the active container instance (if any)"
ACTIVE_ID=$(oci container-instances container-instance list \
  --compartment-id "$OCI_COMPARTMENT_ID" \
  --query "data.items[?\"display-name\"=='${DISPLAY_NAME}' && \"lifecycle-state\"=='ACTIVE'].id | [0]" \
  --raw-output)

if [ -n "$ACTIVE_ID" ] && [ "$ACTIVE_ID" != "null" ]; then
  echo "==> Deleting active instance $ACTIVE_ID"
  oci container-instances container-instance delete --container-instance-id "$ACTIVE_ID" --force
  for i in $(seq 1 30); do
    STATE=$(oci container-instances container-instance get --container-instance-id "$ACTIVE_ID" --query "data.\"lifecycle-state\"" --raw-output)
    echo "  [$i] $STATE"
    [ "$STATE" = "DELETED" ] && break
    sleep 5
  done
else
  echo "==> No active instance found, skipping delete"
fi

echo "==> Creating new container instance"
NEW_ID=$(oci container-instances container-instance create \
  --compartment-id "$OCI_COMPARTMENT_ID" \
  --availability-domain "$OCI_AVAILABILITY_DOMAIN" \
  --display-name "$DISPLAY_NAME" \
  --shape "$SHAPE" \
  --shape-config "{\"ocpus\": $OCPUS, \"memoryInGBs\": $MEMORY_GBS}" \
  --vnics "file://$WORKDIR/vnics.json" \
  --containers "file://$WORKDIR/containers.json" \
  --image-pull-secrets "file://$WORKDIR/pull_secret.json" \
  --container-restart-policy "ALWAYS" \
  --query "data.id" --raw-output)

echo "==> Waiting for $NEW_ID to become ACTIVE"
STATE=""
for i in $(seq 1 30); do
  STATE=$(oci container-instances container-instance get --container-instance-id "$NEW_ID" --query "data.\"lifecycle-state\"" --raw-output)
  echo "  [$i] $STATE"
  [ "$STATE" = "ACTIVE" ] && break
  if [ "$STATE" = "FAILED" ]; then
    echo "Container instance entered FAILED state" >&2
    exit 1
  fi
  sleep 5
done
if [ "$STATE" != "ACTIVE" ]; then
  echo "Timed out waiting for ACTIVE state" >&2
  exit 1
fi

echo "==> Reattaching the reserved public IP"
NEW_VNIC_ID=$(oci container-instances container-instance get --container-instance-id "$NEW_ID" --query "data.vnics[0].\"vnic-id\"" --raw-output)
NEW_PRIVATE_IP_ID=$(oci network private-ip list --vnic-id "$NEW_VNIC_ID" --query "data[0].id" --raw-output)

# The VNIC comes up with an auto-assigned ephemeral public IP
# (isPublicIpAssigned:true on create); OCI refuses to attach a reserved IP
# to a private IP that already has one, so release the ephemeral IP first.
EPHEMERAL_ID=$(oci network public-ip list \
  --compartment-id "$OCI_COMPARTMENT_ID" \
  --scope AVAILABILITY_DOMAIN \
  --availability-domain "$OCI_AVAILABILITY_DOMAIN" \
  --lifetime EPHEMERAL --all \
  --query "data[?\"private-ip-id\"=='${NEW_PRIVATE_IP_ID}'].id | [0]" \
  --raw-output)
if [ -n "$EPHEMERAL_ID" ] && [ "$EPHEMERAL_ID" != "null" ]; then
  echo "==> Releasing ephemeral IP $EPHEMERAL_ID"
  oci network public-ip delete --public-ip-id "$EPHEMERAL_ID" --force
fi

oci network public-ip update \
  --public-ip-id "$OCI_RESERVED_PUBLIC_IP_ID" \
  --private-ip-id "$NEW_PRIVATE_IP_ID"

echo "==> Deploy complete: $NEW_ID"
