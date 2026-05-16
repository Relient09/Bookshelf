# 📚 Bookshelf

A self-hosted book collection manager. Add books by ISBN or title, auto-filled from Open Library. Covers, search, CSV export.

Built with Flask + PostgreSQL.

---

## Deploy on your server (no source code needed)

### 1. Edit `docker-compose.yml`

Replace the image line with your actual GitHub username and repo name:

```yaml
image: ghcr.io/YOUR_GITHUB_USERNAME/YOUR_REPO_NAME:latest
```

### 2. Run it

```bash
docker compose up -d
```

Visit **http://localhost:5000**

That's it. Docker pulls the pre-built image from GHCR automatically.

---

## Update to the latest version

```bash
docker compose pull
docker compose up -d
```

---

## Useful commands

```bash
# View logs
docker compose logs -f web

# Stop
docker compose down

# Stop and wipe database (full reset)
docker compose down -v
```

---

## Repo structure

```
├── app.py                          # Flask backend
├── templates/
│   └── index.html                  # Frontend UI
├── requirements.txt
├── Dockerfile
├── docker-compose.yml              # For deployment (pulls from GHCR)
└── .github/
    └── workflows/
        └── docker-publish.yml      # Auto-builds and pushes image on push to main
```

---

## How the CI/CD works

Every time you push to `main`, GitHub Actions automatically:
1. Builds the Docker image
2. Pushes it to `ghcr.io/YOUR_GITHUB_USERNAME/YOUR_REPO_NAME:latest`

Your server just needs to run `docker compose pull && docker compose up -d` to get the update.

---

## Making the package public (so no login is needed on your server)

1. Go to your GitHub profile → **Packages**
2. Click the `bookshelf` package
3. **Package settings** → Change visibility → **Public**

If you keep it private, run this on your server first:
```bash
echo YOUR_GITHUB_PAT | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
```
