# Week 9 Setup - System Scalability & Resource Utilization
**Goal:** Docker‑compose for Ollama, PostgreSQL, Vector DB, Agent API; add health checks; simulate load, monitor CPU/Memory; produce Docker‑compose + basic Grafana dashboard screenshot.

## Prerequisites
- Completed Week 8 setup (integration, paper trading simulation)
- Docker and Docker Compose installed
- Python virtual environment activated (`source venv/Scripts/activate` or `source RAATS_Test.venv/Scripts/activate`)
- Required packages installed: yfinance, pandas-ta, matplotlib, seaborn (install as needed)
- Ollama with llama3 model running
- Basic understanding of pandas and Jupyter notebooks

## Daily Activities with Runnable Code Snippets

### Monday 28 Sep – Docker‑compose basics & service definitions
1. Ensure virtual environment activated.
2. Install Docker Compose (if not already) and review documentation.
3. Create a `docker-compose.yml` that defines services for:
   - Ollama (LLM service)
   - PostgreSQL (for metadata and trade logs)
   - Chroma (vector store for RAG)
   - Agent API (a FastAPI wrapper that exposes the trading loop)
4. Write a simple Dockerfile for the Agent API.
5. Create the file and commit:
   ```bash
   mkdir -p deployment
   ```
   Then create `deployment/docker-compose.yml` and `deployment/agent/Dockerfile`.
   ```bash
   cat > deployment/docker-compose.yml << 'EOF'
   version: '3.8'
   services:
     ollama:
       image: ollama/ollama:latest
       container_name: ollama
       ports:
         - "11434:11434"
       volumes:
         - ollama_data:/root/.ollama
       restart: unless-stopped
       healthcheck:
         test: ["CMD", "curl", "-f", "http://localhost:11434/api/version"]
         interval: 30s
         timeout: 10s
         retries: 5
     postgres:
       image: postgres:15
       container_name: postgres
       environment:
         POSTGRES_USER: raats
         POSTGRES_PASSWORD: raats_pass
         POSTGRES_DB: raats_db
       ports:
         - "5432:5432"
       volumes:
         - postgres_data:/var/lib/postgresql/data
       restart: unless-stopped
       healthcheck:
         test: ["CMD", "pg_isready", "-U", "raats"]
         interval: 30s
         timeout: 10s
         retries: 5
     chroma:
       image: chromadb/chroma:latest
       container_name: chroma
       ports:
         - "8000:8000"
       volumes:
         - chroma_data:/chroma/chroma
       restart: unless-stopped
       healthcheck:
         test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/heartbeat"]
         interval: 30s
         timeout: 10s
         retries: 5
     agent-api:
       build: ./agent
       container_name: agent_api
       ports:
         - "8000:8000"
       environment:
         - OLLAMA_HOST=ollama:11434
         - POSTGRES_HOST=postgres
         - POSTGRES_PORT=5432
         - POSTGRES_USER=raats
         - POSTGRES_PASSWORD=raats_pass
         - POSTGRES_DB=raats_db
         - CHROMA_HOST=chroma
         - CHROMA_PORT=8000
       depends_on:
         ollama:
           condition: service_healthy
         postgres:
           condition: service_healthy
         chroma:
           condition: service_healthy
       restart: unless-stopped
   volumes:
     ollama_data:
     postgres_data:
     chroma_data:
   EOF
   ```
   ```bash
   mkdir -p deployment/agent
   cat > deployment/agent/Dockerfile << 'EOF'
   FROM python:3.11-slim
   WORKDIR /app
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   COPY . .
   CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
   EOF
   ```
   ```bash
   git add deployment/docker-compose.yml deployment/agent/Dockerfile
   git commit -m "Add docker-compose and agent API Dockerfile"
   git push origin dev
   ```

### Tuesday 29 Sep – Agent API implementation
1. Create a FastAPI application that wraps the trading loop.
2. Write `deployment/agent/main.py` and `deployment/agent/requirements.txt`.
3. Commit the files.

### Wednesday 30 Sep – Health checks and monitoring setup
1. Add Prometheus and Grafana to the docker-compose.
2. Configure Prometheus to scrape metrics from the agent API (if we expose metrics) and from the other services.
3. Create a basic Grafana dashboard JSON.

### Thursday 1 Oct – Load simulation and resource monitoring
1. Write a script to simulate multiple requests to the agent API to generate load.
2. Use `docker stats` or Prometheus to monitor CPU/Memory.

### Friday 2 Oct – Morning: Finalize docker-compose and generate Grafana dashboard
1. Ensure all services are healthy.
2. Take a screenshot of the Grafana dashboard showing key metrics.
3. Afternoon: Rest (no work).

### Saturday 3 Oct – Rest day
- No planned project work.

### Sunday 4 Oct – Preparation for Week 10
1. Review Week 10 plan: Evaluation Framework.
2. Sketch how to write an evaluation script that computes Sharpe ratio, max drawdown, etc.
3. Write a brief note in journal/week9_prep_week10.md.
4. Commit any notes or small scripts.
5. Create reflection for Week 9.
   ```markdown
   # Week 9 Reflection – Luyolo Nyaluza
   ## What went well
   - Successfully defined docker-compose services for Ollama, PostgreSQL, Chroma, and Agent API.
   - Created Dockerfile for the Agent API.
   - Added health checks for each service.
   ## Challenges / Blockers
   - Learning curve for Docker Compose networking.
   - Ensuring the Agent API can connect to all services.
   ## Goals for Week 10
   - Write evaluation script for backtesting.
   - Compute performance metrics (Sharpe, max drawdown, etc.).
   - Compare baseline vs LLM‑guided strategy.
   ```
6. Commit reflection and prep note.
   ```bash
   mkdir -p journal
   cat > journal/week9_reflection.md << 'EOF'
   [content above]
   EOF
   ```
   ```bash
   cat > journal/week9_prep_week10.md << 'EOF'
   # Week 10 Preparation Notes
   ## Topic: Evaluation Framework
   
   ## High-level architecture ideas:
   - Backtest the LLM‑guided strategy over historical data.
   - Compute metrics: cumulative return, Sharpe ratio, max drawdown, win rate.
   - Compare with a baseline (e.g., buy and hold, or SMA crossover).
   - Generate a report (PDF or MD).
   
   ## Components to develop:
   1. Backtesting engine (can use backtrader or zipline, or custom).
   2. Metrics calculator.
   3. Report generator.
   
   ## Next steps:
   - Choose a backtesting library.
   - Write the evaluation script.
   - Run the backtest and produce the report.
   EOF
   ```
   ```bash
   git add journal/week9_reflection.md journal/week9_prep_week10.md
   git commit -m "Add week 9 reflection and week 10 prep"
   git push origin dev
   ```

---\n**End of Week 9 Deliverables:**\n- Module: deployment/docker-compose.yml, deployment/agent/Dockerfile, deployment/agent/requirements.txt, deployment/agent/main.py\n- Logs: journal/week9_reflection.md\n- Preparation: journal/week9_prep_week10.md\n