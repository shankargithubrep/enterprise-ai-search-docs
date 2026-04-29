# VM Hosting & Scaling Strategy

> **Runtime:** Bare Python process (no Docker, no Kubernetes) · **OS:** Ubuntu 22.04 or RHEL 8+ · **Instance:** m6i.xlarge · **Management:** systemd

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [VM Sizing](#vm-sizing)
- [Connector Process Layout](#connector-process-layout)
- [systemd Service Configuration](#systemd-service-configuration)
- [Multi-Connector Single VM](#multi-connector-single-vm)
- [Scaling Strategy](#scaling-strategy)
  - [Horizontal Scaling (Add VMs)](#horizontal-scaling-add-vms)
  - [Vertical Scaling (Bigger VM)](#vertical-scaling-bigger-vm)
  - [Regional Scaling](#regional-scaling)
- [Staggered Sync Schedules](#staggered-sync-schedules)
- [Health Monitoring](#health-monitoring)
- [Secret Management](#secret-management)
- [OS Hardening](#os-hardening)

---

## Architecture Overview

```
Region: us-east-1
┌──────────────────────────────────────────────────────────┐
│                    Elasticsearch Cluster                   │
│               (Elastic Cloud / Self-managed)               │
└────────────────────────▲─────────────────────────────────┘
                         │ HTTPS (port 443)
                         │ API Key auth
         ┌───────────────┼───────────────┐
         │               │               │
┌────────┴──────┐ ┌──────┴───────┐ ┌─────┴────────┐
│   VM 1        │ │   VM 2       │ │   VM 3       │
│ m6i.xlarge    │ │ m6i.xlarge   │ │ m6i.xlarge   │
│               │ │              │ │              │
│ Tenant A SP   │ │ Tenant D SP  │ │ Tenant G SP  │
│ Tenant A SF   │ │ Tenant E SP  │ │ Tenant H SP  │
│ Tenant B SP   │ │ Tenant E SF  │ │ Tenant I SP  │
│ Tenant C SP   │ │ Tenant F SP  │ │ Tenant J SP  │
│               │ │              │ │              │
│ ~10 connectors│ │ ~10 connectors│ │ ~10 connectors│
└───────────────┘ └──────────────┘ └──────────────┘

SP = SharePoint Online connector
SF = Salesforce connector
```

Each VM runs a single Elastic connector service process (Python). That process manages multiple connectors via the `connectors` array in `config.yml`. Each connector syncs independently on its own schedule.

---

## VM Sizing

| Instance | vCPU | Memory | Network | Connectors per VM | Use Case |
|---|---|---|---|---|---|
| `m6i.large` | 2 | 8 GB | Up to 12.5 Gbps | 3-5 | Development, small tenants |
| **`m6i.xlarge`** | **4** | **16 GB** | **Up to 12.5 Gbps** | **10-15** | **Production (recommended)** |
| `m6i.2xlarge` | 8 | 32 GB | Up to 12.5 Gbps | 20-30 | High-volume tenants |

**Why m6i.xlarge is the sweet spot:**

The connector process is I/O-bound (waiting on Graph API, Tika extraction, Elasticsearch bulk writes), not CPU-bound. 4 vCPUs handle 10-15 concurrent connectors comfortably because:

- Only 1-3 connectors sync simultaneously (staggered schedules)
- Each sync is mostly network wait time (Graph API round-trips)
- Tika extraction is the CPU-intensive phase — ~80% idle between documents
- Memory: Python process + Tika JVM + OS ≈ 4 GB at peak; 16 GB provides headroom for JVM GC spikes

Going larger than m6i.xlarge wastes money — the bottleneck is Microsoft Graph API throttling (10,000 requests / 10 min per app), not VM resources.

---

## Connector Process Layout

```
/opt/elastic-connectors/
├── .venv/                          # Python 3.10+ virtual environment
│   └── bin/python                  # Python interpreter
├── connectors/                     # Connector framework source
│   ├── service.py                  # Main entry point
│   └── ...
├── config.yml                      # Connector + ES configuration
├── requirements.txt                # Python dependencies
└── logs/                           # Application logs (if file logging enabled)
```

### Installation Steps

```bash
# Prerequisites
sudo apt update && sudo apt install -y python3.10 python3.10-venv python3.10-dev git

# Create service user (no login shell, no home directory)
sudo useradd -r -s /usr/sbin/nologin elastic-connector

# Clone and install
sudo mkdir -p /opt/elastic-connectors
sudo git clone https://github.com/elastic/connectors.git /opt/elastic-connectors
cd /opt/elastic-connectors
sudo git checkout v9.0.0  # Match your ES version

# Virtual environment
sudo python3.10 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt

# Configuration
sudo cp config.yml.example config.yml
# Edit config.yml (see next section)

# Permissions
sudo chown -R elastic-connector:elastic-connector /opt/elastic-connectors
sudo chmod 600 config.yml  # config contains API keys
```

---

## systemd Service Configuration

### Primary Service File

`/etc/systemd/system/elastic-connector.service`

```ini
[Unit]
Description=Elastic Connector Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=elastic-connector
Group=elastic-connector
WorkingDirectory=/opt/elastic-connectors
ExecStart=/opt/elastic-connectors/.venv/bin/python -m connectors.service
Restart=always
RestartSec=30
StartLimitIntervalSec=300
StartLimitBurst=5

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=elastic-connector

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/elastic-connectors/logs
PrivateTmp=true

# Environment
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

### Service Management

```bash
# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable elastic-connector
sudo systemctl start elastic-connector

# Check status
sudo systemctl status elastic-connector

# View logs
sudo journalctl -u elastic-connector -f              # follow live
sudo journalctl -u elastic-connector --since "1h ago" # last hour
sudo journalctl -u elastic-connector -p err           # errors only

# Restart after config change
sudo systemctl restart elastic-connector
```

---

## Multi-Connector Single VM

A single connector service process manages multiple connectors. Each connector is an entry in the `connectors` array in `config.yml`:

```yaml
connectors:
  # Tenant A - SharePoint
  - connector_id: abc123-sharepoint
    service_type: sharepoint_online
    api_key: BASE64_API_KEY_A_SP

  # Tenant A - Salesforce
  - connector_id: abc123-salesforce
    service_type: salesforce
    api_key: BASE64_API_KEY_A_SF

  # Tenant B - SharePoint
  - connector_id: def456-sharepoint
    service_type: sharepoint_online
    api_key: BASE64_API_KEY_B_SP

  # Tenant C - SharePoint
  - connector_id: ghi789-sharepoint
    service_type: sharepoint_online
    api_key: BASE64_API_KEY_C_SP

elasticsearch.host: https://YOUR_DEPLOYMENT.us-east-2.aws.elastic-cloud.com:443
elasticsearch.api_key: BASE64_ES_API_KEY
elasticsearch.ssl: true
elasticsearch.verify_certs: true

service.log_level: INFO
service.idling: 30
```

**Key behaviors:**

- Each connector syncs independently on its own schedule (set via Kibana or Connector API)
- The service polls `.elastic-connectors` every `service.idling` seconds (default 30) for pending sync jobs
- If multiple connectors have pending jobs, they execute sequentially within the process
- The `api_key` per connector is scoped to that connector's index — principle of least privilege

---

## Scaling Strategy

### Horizontal Scaling (Add VMs)

When a VM reaches 10-15 connectors, add a new VM:

1. Provision a new `m6i.xlarge` instance
2. Clone the connector framework (same version)
3. Create a `config.yml` with the next batch of connectors
4. Install the systemd service
5. Start the service

**Connector assignment rules:**

- Keep all connectors for a single tenant on the same VM (simplifies debugging)
- Balance by sync frequency, not connector count — 2 tenants with hourly syncs ≠ 10 tenants with daily syncs
- Spread SharePoint connectors across VMs — they are the heaviest (Graph API + Tika extraction)

### Vertical Scaling (Bigger VM)

Only scale vertically if:
- A single tenant has very large document libraries (>100K files)
- Tika extraction is CPU-bound during full syncs
- You need >15 connectors on a single VM due to cost constraints

Upgrade path: `m6i.xlarge` → `m6i.2xlarge` (doubles CPU and memory).

### Regional Scaling

For multi-region deployments:

```
Region us-east-1:  3 VMs × 10 connectors = 30 tenants
Region eu-west-1:  2 VMs × 10 connectors = 20 tenants
Region ap-south-1: 1 VM  × 10 connectors = 10 tenants
```

Each region has its own Elasticsearch cluster. Connector VMs in each region connect to that region's cluster only.

**Scaling formula:**

```
VMs per region = ceil(tenants_in_region / 10)
```

At 1,200 tenants across 21 regions ≈ 57 tenants/region ≈ 6 VMs/region ≈ 126 VMs globally.

---

## Staggered Sync Schedules

When 10 connectors share a VM, stagger their sync times to avoid overlapping Graph API calls and Tika CPU spikes:

```
Tenant A:  incremental at 00:00, 06:00, 12:00, 18:00
Tenant B:  incremental at 00:30, 06:30, 12:30, 18:30
Tenant C:  incremental at 01:00, 07:00, 13:00, 19:00
Tenant D:  incremental at 01:30, 07:30, 13:30, 19:30
...
```

Set via Connector API:

```json
PUT _connector/tenant-a-sharepoint/_scheduling
{
  "scheduling": {
    "incremental": { "enabled": true, "interval": "0 0,6,12,18 * * *" },
    "full":        { "enabled": true, "interval": "0 3 * * 0" }
  }
}

PUT _connector/tenant-b-sharepoint/_scheduling
{
  "scheduling": {
    "incremental": { "enabled": true, "interval": "30 0,6,12,18 * * *" },
    "full":        { "enabled": true, "interval": "30 3 * * 0" }
  }
}
```

**Full syncs** should all run during off-peak hours (e.g., Sunday early morning), staggered by 30-60 minutes:

```
Tenant A full:  Sunday 03:00
Tenant B full:  Sunday 03:30
Tenant C full:  Sunday 04:00
...
```

---

## Health Monitoring

### Connector Check-In Monitoring

Each connector reports its `last_seen` timestamp to `.elastic-connectors`. If a connector VM dies, the `last_seen` stops updating.

```json
// Connectors that haven't checked in for 5 minutes
GET .elastic-connectors/_search
{
  "query": {
    "range": {
      "last_seen": {
        "lt": "now-5m"
      }
    }
  },
  "_source": ["name", "last_seen", "status", "index_name"]
}
```

### Kibana Alerting Rule — Stale Connector

Create in **Stack Management → Rules → Create Rule → Elasticsearch query**:

| Setting | Value |
|---|---|
| Rule type | Elasticsearch query |
| Index | `.elastic-connectors` |
| Query | `{ "range": { "last_seen": { "lt": "now-5m" } } }` |
| Threshold | `> 0` |
| Check every | 2 minutes |
| Action | Slack webhook / PagerDuty / email |

Alert message template:

```
Connector {{context.title}} has not checked in since {{context.last_seen}}.
VM may be down. Check: sudo systemctl status elastic-connector
Index: {{context.index_name}}
```

### Sync Failure Monitoring

```json
// Failed sync jobs in last 24 hours
GET .elastic-connector-sync-jobs/_search
{
  "size": 10,
  "sort": [{ "started_at": "desc" }],
  "query": {
    "bool": {
      "filter": [
        { "term": { "status": "error" } },
        { "range": { "started_at": { "gte": "now-24h" } } }
      ]
    }
  },
  "_source": ["connector.id", "connector.name", "error", "started_at"]
}
```

### VM-Level Monitoring

Install the Elastic Agent on each connector VM to collect:

| Metric | Alert Threshold | Action |
|---|---|---|
| CPU utilization | > 80% sustained 10 min | Scale up or redistribute connectors |
| Memory utilization | > 85% | Check for Tika memory leak, restart service |
| Disk usage | > 80% | Clean logs, extend volume |
| Process up/down | Process not running | systemd auto-restarts; alert if restart loop |

---

## Secret Management

### Option A — AWS Secrets Manager (Recommended)

Store API keys and Azure AD credentials in AWS Secrets Manager. Retrieve at service startup:

```bash
# /opt/elastic-connectors/fetch-secrets.sh
#!/bin/bash
SECRET=$(aws secretsmanager get-secret-value \
  --secret-id elastic-connector/us-east-1 \
  --query SecretString --output text)

export ES_API_KEY=$(echo $SECRET | jq -r '.es_api_key')
export CONNECTOR_API_KEY=$(echo $SECRET | jq -r '.connector_api_key')
```

Update systemd to use the wrapper:

```ini
ExecStart=/bin/bash -c 'source /opt/elastic-connectors/fetch-secrets.sh && /opt/elastic-connectors/.venv/bin/python -m connectors.service'
```

### Option B — File-Based (Simple)

Store API keys in `config.yml` with strict file permissions:

```bash
sudo chmod 600 /opt/elastic-connectors/config.yml
sudo chown elastic-connector:elastic-connector /opt/elastic-connectors/config.yml
```

**Secret rotation schedule:**

| Secret | Rotation interval | Process |
|---|---|---|
| Elasticsearch API key | 12 months | Generate new key → update config.yml → restart service |
| Azure AD client secret | 12 months (set 24-month expiry, rotate at 12) | Renew in Azure Portal → update connector config via Kibana → restart service |
| Salesforce OAuth tokens | Auto-refresh | Connector handles token refresh automatically |

---

## OS Hardening

### Minimum Security Configuration

```bash
# Automatic security updates
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades

# Firewall — only allow outbound HTTPS
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw enable

# Disable root login
sudo sed -i 's/PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
sudo systemctl restart sshd

# Log rotation for connector logs
sudo cat > /etc/logrotate.d/elastic-connector << 'EOF'
/opt/elastic-connectors/logs/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 elastic-connector elastic-connector
    postrotate
        systemctl restart elastic-connector
    endscript
}
EOF
```

---

*Last updated: April 2026 · Connector framework v9.x · AWS EC2 deployment*
