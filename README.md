🧙‍♂️ Rincewind: Universal Email Gateway (v2.4.0)
Rincewind is the central traffic controller for the TechnoShed email ecosystem. It polls a central inbox and intelligently routes requests to various internal services based on the recipient address.

🚀 Key Features
Multi-Lane Routing: Dynamically handles translations@ and uploads@ traffic.

Document Translation: Integrated with Google Cloud Translate v3 for .docx and .pdf (up to 20 pages).

Text Fallback: Automatically translates email body text if no documents are attached.

System Heartbeat: Verifies Google Cloud, IMAP, and SMTP connectivity at startup.

Bilingual Help: Detects user language to provide translated system manuals automatically.

🏗 Architecture
Rincewind is a Docker Swarm Service designed to run across a distributed cluster (e.g., Raspberry Pi and NUC nodes).

Overlay Network: Operates on a private overlay mesh to communicate with other services without exposing internal ports.

Local Registry: Uses a private registry on the cluster manager to distribute "baked" images instantly across all nodes, eliminating startup build delays.

Persistence: Utilizes central storage mounts for real-time code updates and file hosting.

🛠 Deployment
Swarm (Recommended)
Before deploying, build the "baked" image and push it to your internal registry so all nodes can access it instantly.

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
processor.py: The main Python engine (v2.4.0) featuring the heartbeat and routing logic.

Dockerfile: Defines the pre-configured environment for fast scaling.

docker-compose.yml: The production Swarm stack definition.

docker-compose-standalone.yml: Legacy configuration for standalone deployment.

.env.example: Template for required API keys and credentials.

🔐 Security SOP
Credentials: Never commit your .env or Google Cloud .json keys to the repository.

Paths: Ensure your local storage mount paths in docker-compose.yml match your specific environment.