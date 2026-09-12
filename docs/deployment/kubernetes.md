# Kubernetes Deployment

Deploy ReviewSentinel to Kubernetes to decouple the webhook server from job execution. The server pod receives webhooks and dispatches each review as a separate Kubernetes Job, enabling horizontal scaling with no shared process state.

## Architecture

```
GitHub/GitLab webhook
        │
        ▼
┌──────────────────────┐
│  Webhook Server Pod  │
│  (aiohttp)           │
└──────────┬───────────┘
           │ POST /apis/batch/v1/...
           ▼
┌──────────────────────┐       ┌─────────┐
│  Kubernetes Job      │──────▶│  Redis   │
│  review-sentinel run-job│       │ (conversations)
└──────────────────────┘       └─────────┘
```

**Server pod** — runs the webhook server. When `kubernetes.image` is set in the config, the Kubernetes job runner is automatically enabled. On each webhook event, it serializes a `JobPayload` and creates a Kubernetes Job via the in-cluster API.

**Job pod** — runs `review-sentinel run-job`, deserializes the payload, calls the LLM provider API, and posts results back to the PR. Each job is independent and short-lived.

**Redis** — required for K8s mode. Provides per-PR job serialization via Redis queues and stores conversation history so multi-turn interactions work across separate Job pods.

## What Changes vs. Standalone

| | Standalone | Kubernetes |
|---|---|---|
| Job execution | Same process, asyncio queue | Separate K8s Job pod per event |
| Agent runner | Claude Code CLI (default) or LLM provider API | LLM provider API (requires `agent.reviewer.provider`) |
| Conversation store | In-memory | Redis (required) |
| Scaling | Single process | Unlimited concurrent Jobs |

## Container Image

Pre-built images are published to GitHub Container Registry on every merge to `main`:

```
ghcr.io/rohan1857/review-sentinel:latest
ghcr.io/rohan1857/review-sentinel:<sha>
```

Provider-specific images (smaller, single-provider installs) are also available:

```
ghcr.io/rohan1857/review-sentinel-anthropic:latest
ghcr.io/rohan1857/review-sentinel-openai:latest
ghcr.io/rohan1857/review-sentinel-google:latest
```

To build locally:

```bash
make -C deploy build                              # tags as ghcr.io/rohan1857/review-sentinel:latest
make -C deploy build IMAGE_TAG=dev                # tags as ghcr.io/rohan1857/review-sentinel:dev
docker build -f ci/Dockerfile -t my-image:v1 .    # fully custom tag
```

## Getting Started

These steps work with any Kubernetes cluster (minikube, kind, Docker Desktop, EKS, GKE, etc.). See [Local Development with Minikube](#minikube) below for minikube-specific tips.

### 1. Create Your Secrets File

```bash
cp deploy/k8s/secret.yaml.template deploy/k8s/secret.yaml
```

Edit `deploy/k8s/secret.yaml` with your credentials:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: review-sentinel-secrets
  namespace: review-sentinel
type: Opaque
stringData:
  GITHUB_APP_ID: "12345"
  GITHUB_INSTALLATION_ID: "67890"
  GITHUB_WEBHOOK_SECRET: "your-webhook-secret"
  GITHUB_APP_PRIVATE_KEY: |
    -----BEGIN RSA PRIVATE KEY-----
    ...
    -----END RSA PRIVATE KEY-----
  ALLOWED_USERS: "alice,bob"
  ALLOWED_REPOS: "your-org/your-repo"
  GOOGLE_API_KEY: "AIza..."
```

All secrets go in this file. Non-secret config (bot username, triggers, provider) lives in `deploy/k8s/base/config.yaml`.

### 2. Deploy

```bash
make -C deploy deploy
```

This applies the kustomize overlay (namespace, RBAC, Redis, server deployment, secrets) and waits for the rollout to complete. By default it pulls the `latest` image from GHCR. To pin a specific version:

```bash
make -C deploy deploy IMAGE_TAG=1.2.3
```

### 3. Verify

```bash
# Check all resources are running
make -C deploy status

# Expected output:
# NAME                                       READY   STATUS    AGE
# pod/review-sentinel-server-xxx                1/1     Running   30s
# pod/redis-xxx                              1/1     Running   30s
# ...
```

### 4. Expose the Server

Forward the K8s service to your local machine:

```bash
make -C deploy port-forward
# Forwarding localhost:8080 → service/review-sentinel-server:80
```

For GitHub/GitLab webhooks to reach your local server, use a tunnel in a separate terminal:

```bash
cloudflared tunnel --url http://localhost:8080
# or: ngrok http 8080
# or: tailscale funnel 8080
```

Use the tunnel URL as your webhook Payload URL (e.g. `https://abc123.trycloudflare.com/webhooks/github`).

### 5. Tail Logs

```bash
# Server pod logs
make -C deploy logs

# Specific job pod logs
kubectl -n review-sentinel logs job/<job-name>
```

### 6. Tear Down

```bash
make -C deploy teardown
```

Deletes the entire `review-sentinel` namespace and all resources within it (pods, jobs, services, secrets, configmaps).

## Local Development with Minikube {: #minikube }

[Minikube](https://minikube.sigs.k8s.io/docs/start/) runs a single-node Kubernetes cluster locally. The steps above work as-is with minikube — the image is pulled from GHCR. A few tips for local iteration:

### Building Images Locally

To test code changes without pushing to a registry, build the image directly into minikube's Docker daemon:

```bash
eval $(minikube docker-env)
make -C deploy build IMAGE_TAG=dev
```

Then deploy with that tag and `Never` pull policy so minikube uses the local image:

```bash
make -C deploy deploy IMAGE_TAG=dev
```

You may need to set `imagePullPolicy: Never` in the deployment to prevent minikube from trying to pull from a registry. Patch it after deploying:

```bash
kubectl -n review-sentinel patch deployment review-sentinel-server \
  -p '{"spec":{"template":{"spec":{"containers":[{"name":"server","imagePullPolicy":"Never"}]}}}}'
```

### Port Forwarding

Minikube does not expose LoadBalancer services to the host by default. Use `make -C deploy port-forward` or `minikube tunnel` to access the service.

## CI Deployment (Automated)

For CI pipelines (e.g. GitHub Actions testing), use `deploy-ci` which creates secrets from environment variables instead of a file. Pass `IMAGE_TAG` to pin the deployment to a specific build:

```bash
export TEST_GITHUB_TOKEN=ghp_...
export GOOGLE_API_KEY=AIza...

make -C deploy deploy-ci IMAGE_TAG=$(git rev-parse HEAD)
```

This creates the namespace, populates the secret from env vars (including `K8S_IMAGE` for job pods), applies the CI overlay, and pins the server deployment to the specified image tag.

## Production Cluster

### Create an Overlay

Create a new overlay directory for your cluster:

```bash
mkdir -p deploy/production
```

Create a `kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: review-sentinel
resources:
  - ../k8s/base
patchesStrategicMerge:
  - deployment-patch.yaml
configMapGenerator:
  - name: review-sentinel-config
    namespace: review-sentinel
    behavior: replace
    files:
      - config.yaml
    options:
      disableNameSuffixHash: true
```

Create a `config.yaml` with your production settings:

```yaml
reviewer:
  bot_username: "review_sentinelbot"
  triggers:
    - pr_opened

agent:
  provider: "anthropic"

redis:
  url: "redis://redis.review-sentinel.svc.cluster.local:6379/0"

kubernetes:
  image: "your-registry.com/review-sentinel:latest"
  namespace: "review-sentinel"
  image_pull_policy: "Always"
  active_deadline_seconds: 600
  env_from_secrets:
    - "review-sentinel-secrets"
```

Create a `deployment-patch.yaml` to override the container image:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: review-sentinel-server
  namespace: review-sentinel
spec:
  template:
    spec:
      containers:
        - name: server
          image: your-registry.com/review-sentinel:latest
          imagePullPolicy: Always
```

Create secrets in the namespace:

```bash
kubectl -n review-sentinel create secret generic review-sentinel-secrets \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-... \
  --from-literal=GITHUB_TOKEN=ghp_... \
  --from-literal=GITHUB_WEBHOOK_SECRET=your-secret
```

Deploy:

```bash
kubectl apply -k deploy/production
```

### Ingress

The service exposes port 80 internally. Configure an Ingress or load balancer to route external webhook traffic:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: review-sentinel
  namespace: review-sentinel
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt
spec:
  tls:
    - hosts: [bot.example.com]
      secretName: review-sentinel-tls
  rules:
    - host: bot.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: review-sentinel-server
                port:
                  number: 80
```

Then set your GitHub/GitLab webhook URL to `https://bot.example.com/webhooks/github`.

## Config File

The K8s config lives at `deploy/k8s/base/config.yaml` and is mounted into the server pod at `/etc/review-sentinel/config.yaml` via a ConfigMap. It extends the shared app config with Redis and Kubernetes-specific settings:

```yaml
webhook:
  host: "0.0.0.0"
  port: 8080

reviewer:
  bot_username: "review_sentinelbot"
  triggers:
    - pr_opened

agent:
  provider: "google"

redis:
  url: "redis://redis.review-sentinel.svc.cluster.local:6379/0"

kubernetes:
  image: "ghcr.io/rohan1857/review-sentinel:latest"
  namespace: "review-sentinel"
  image_pull_policy: "Always"
  active_deadline_seconds: 600
  env_from_secrets:
    - "review-sentinel-secrets"
```

The `redis` and `kubernetes` sections are what distinguish K8s mode from standalone. When `kubernetes.image` is set, the server automatically uses the Kubernetes job runner instead of the in-process runner.

## Kubernetes Configuration Reference

| YAML path | Env var | Default | Description |
|---|---|---|---|
| `kubernetes.image` | `K8S_IMAGE` | — | Container image for Job pods. Enables the K8s runner |
| `kubernetes.namespace` | `K8S_NAMESPACE` | `default` | Namespace for spawned Job pods |
| `kubernetes.image_pull_policy` | `K8S_IMAGE_PULL_POLICY` | — | `Always`, `Never`, or `IfNotPresent` |
| `kubernetes.service_account` | `K8S_SERVICE_ACCOUNT` | — | ServiceAccount for Job pods |
| `kubernetes.env_from_secrets` | `K8S_ENV_FROM_SECRETS` | — | Comma-separated Secret names to mount as env vars |
| `kubernetes.backoff_limit` | `K8S_BACKOFF_LIMIT` | `0` | Job retry attempts |
| `kubernetes.active_deadline_seconds` | `K8S_ACTIVE_DEADLINE_SECONDS` | `600` | Per-job timeout in seconds |
| `kubernetes.ttl_after_finished` | `K8S_TTL_AFTER_FINISHED` | `3600` | Seconds before completed Jobs are cleaned up |
| `kubernetes.resources.requests.cpu` | `K8S_RESOURCE_REQUESTS_CPU` | — | CPU request for Job pods |
| `kubernetes.resources.requests.memory` | `K8S_RESOURCE_REQUESTS_MEMORY` | — | Memory request for Job pods |
| `kubernetes.resources.limits.cpu` | `K8S_RESOURCE_LIMITS_CPU` | — | CPU limit for Job pods |
| `kubernetes.resources.limits.memory` | `K8S_RESOURCE_LIMITS_MEMORY` | — | Memory limit for Job pods |
| `redis.url` | `REDIS_URL` | — | Redis connection URL (required for K8s mode) |
| `redis.key_ttl_seconds` | `REDIS_KEY_TTL_SECONDS` | `86400` | TTL for Redis conversation keys |

See [Configuration](../reference/configuration.md) for the full YAML schema and [Environment Variables](../reference/env-vars.md) for the complete variable reference.

## Job Serialization

When multiple webhook events arrive for the same PR, only one K8s Job runs at a time. This prevents race conditions, duplicate reviews, and wasted compute.

The server uses Redis for two purposes:

1. **Per-PR job queue** — each PR key (`platform:repo:pr_number:bot_type`) gets its own Redis list. Jobs are pushed onto the list and consumed serially.
2. **Event-driven completion** — when a Job pod finishes, it publishes a completion signal to a Redis pub/sub channel. The server subscribes and moves on to the next queued job immediately — no K8s API polling.

If a Job pod crashes before publishing its completion signal, the server-side timeout (`active_deadline_seconds` + 10s margin) fires and the consumer moves on.

## RBAC

The server pod needs permission to create and manage Jobs. The base manifests include a ServiceAccount (`review-sentinel-server`) with a Role that grants:

```yaml
rules:
  - apiGroups: ["batch"]
    resources: ["jobs"]
    verbs: ["create", "get", "list", "watch", "delete"]
```

This is namespace-scoped — the server can only manage Jobs in its own namespace.

## Monitoring

- **Health checks** — the server pod exposes `/health` with liveness (30s) and readiness (10s) probes configured in the base deployment.
- **Job status** — `kubectl -n review-sentinel get jobs` shows running and completed review jobs. Jobs are labeled with `review-sentinel/platform`, `review-sentinel/repo`, and `review-sentinel/pr-number` for filtering.
- **Logs** — `make -C deploy logs` tails the server pod. For job pod logs: `kubectl -n review-sentinel logs job/<job-name>`.
