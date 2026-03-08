🧙‍♂️ Rincewind: Universal Email Gateway (v2.4.0)
Rincewind is the traffic cop for the TechnoShed email ecosystem. It polls a central GMX inbox and routes requests to various internal services based on the To: address.

🚀 Key Features
Multi-Lane Routing: Dynamically handles translations@ and uploads@ traffic.

Document Translation: Integrated with Google Cloud Translate v3 for .docx and .pdf (up to 20 pages).

Text Fallback: Automatically translates email body text if no documents are attached.

System Heartbeat: Verifies GCP, GMX (IMAP), and SMTP2GO connectivity at startup.

Bilingual Help: Detects user language to provide translated system manuals.

🏗 Architecture
Rincewind is now a Docker Swarm Service designed to run across the TechnoShed cluster (tspi1, tspi2, and jellyfin).

Overlay Network: Operates on the technoshed_mesh to communicate internally with other services without exposing ports.

Local Registry: Uses a private registry at 10.0.1.1:5000 to distribute "baked" images instantly across nodes, eliminating 10-minute pip install waits.

Persistence: Mounts from the central NFS share (/mnt/ssd/) for real-time code updates and file hosting.

🛠 Deployment
Swarm (Recommended)
Before deploying to the cluster, you must build the "baked" image and push it to your internal registry so all nodes can access it without individual build times.

Bash
# 1. Build and push the baked image to your local registry
docker build -t <<MANAGER_IP>>:5000/rincewind:v2.4.0 .
docker push <<MANAGER_IP>>:5000/rincewind:v2.4.0

# 2. Deploy the stack to the cluster
docker stack deploy -c docker-compose.yml rincewind
Standalone (Legacy)
For single-node testing or non-Swarm environments, use the provided legacy compose file:

Bash
docker-compose -f docker-compose-standalone.yml up -d
📂 Repository Structure
processor.py: The main Python engine (v2.4.0) featuring the heartbeat and multi-lane routing.

Dockerfile: Defines the "baked" environment to eliminate startup latency.

docker-compose.yml: The production Swarm stack definition.

docker-compose-standalone.yml: A legacy configuration for standalone container deployment.

.env.example: A template for your environment variables (GCP, GMX, and SMTP2GO credentials).

🔐 Security SOP
Credentials: Never commit your .env or Google Cloud .json keys to the repository [cite: 2025-12-05].

Paths: Ensure your local NFS mount paths in docker-compose.yml match your specific environment (e.g., <<STORAGE_PATH>>).